"""One launch attempt; the service owns the outcome and any retry policy."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from ..platform import LockHeld, NetworkIsolationError, Platform
from .backup import backup_directory, publish_known_good, snapshot_profile
from .preflight import check_prerequisites, preflight

SHUTDOWN_GRACE_SECONDS = 45  # Match the legacy supervisor's stop_grace.
_SETTLED_REASONS = frozenset({"finish", "stop", "max_runs", "wins", "goal", "no_target"})


class GameBusy(Exception):
    """Another launcher or game instance is active (exit 1)."""


@contextmanager
def _shutdown_request() -> Iterator[Callable[[], float | None]]:
    requested_at: float | None = None

    def request_stop(_signum, _frame):
        nonlocal requested_at
        if requested_at is None:
            requested_at = time.monotonic()

    signals = (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", None), getattr(signal, "SIGQUIT", None))
    previous = {sig: signal.signal(sig, request_stop) for sig in signals if sig is not None}
    try:
        yield lambda: requested_at
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _terminal_status(profile: Path) -> dict:
    try:
        status = json.loads((profile / "farmer_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return status if isinstance(status, dict) else {}


def run_attempt(
    os_: Platform, profile: Path, preset: Path | None, session_id: str | None, *, take_service_lock: bool = False,
) -> int:
    game, info = check_prerequisites(os_, profile)
    with ExitStack() as locks:
        if take_service_lock:
            # The CLI takes this lock; an already-running service holds it itself.
            path = os_.app_data_dir() / "service.lock"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                locks.enter_context(os_.acquire_lock(path))
            except LockHeld as exc:
                raise GameBusy(f"already running (lock {path})") from exc
        try:
            locks.enter_context(os_.acquire_lock(profile / "farmer.run.lock"))
        except LockHeld as exc:
            raise GameBusy("another farmer launcher holds the lock") from exc
        if os_.game_running():
            raise GameBusy("the game is already running; close it first")
        plan = preflight(game, info, profile, preset)
        if session_id:
            warning = os_.check_network_isolation()
            if warning:
                print(f"midgard-farm-service: {warning}", file=sys.stderr)
        backups = backup_directory(os_)
        snapshot_profile(profile, backups)
        if plan.config is not None:
            os_.write_atomic(profile / "farmer.cfg", plan.config)
        (profile / "farmer_stop").unlink(missing_ok=True)
        (profile / "farmer_status.json").unlink(missing_ok=True)
        farmer_log = profile / "farmer.log"
        if farmer_log.is_file():
            os_.replace_atomic(farmer_log, profile / "farmer.log.prev")

        log_dir = os_.app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "FARMER_SESSION": "1"}
        if session_id:
            env["FARMER_SESSION_ID"] = session_id
        else:
            env.pop("FARMER_SESSION_ID", None)
        with (
            tempfile.NamedTemporaryFile(dir=log_dir, prefix="run-", suffix=".log", delete=False) as log,
            open(log.name, "rb") as output,
        ):
            def tee() -> None:
                while chunk := output.read(65536):
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()

            forced = False
            try:
                with (
                    _shutdown_request() as shutdown_requested_at,
                    os_.spawn_tree(plan.argv, cwd=Path(plan.argv[0]).parent, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, isolate_network=bool(session_id)) as tree,
                ):
                    stop_sent = False
                    while True:
                        tee()
                        timeout = 0.05
                        if (requested_at := shutdown_requested_at()) is not None:
                            if not stop_sent:
                                try:
                                    (profile / "farmer_stop").touch()
                                except OSError as exc:
                                    print(f"midgard-farm-service: could not write farmer_stop: {exc}", file=sys.stderr)
                                stop_sent = True
                            timeout = min(timeout, max(0.0, requested_at + SHUTDOWN_GRACE_SECONDS - time.monotonic()))
                        try:
                            code = tree.wait(timeout=timeout)
                            break
                        except subprocess.TimeoutExpired:
                            if timeout == 0:
                                forced = True
                                tree.kill()
                                code = tree.wait()
                                break
            except NetworkIsolationError as exc:
                tee()
                raise NetworkIsolationError(f"{exc}; see {log.name}") from exc
            else:
                tee()

        code = code if code >= 0 else 128 - code
        status = _terminal_status(profile)
        phase, failed, reason = status.get("phase"), status.get("failed"), status.get("finish_reason")
        # A Linux headless finish SIGKILLs itself only after the farmer verifies
        # its flush. On Windows a hard exit does not report a reliable code.
        if not forced and phase == "done" and not failed and (not os_.game_exit_status_reliable or code in (0, 137)):
            print(f"farmer: finished cleanly (exit {code} reason={reason or ''})")
            if session_id and isinstance(reason, str) and reason in _SETTLED_REASONS:
                try:
                    publish_known_good(os_, profile, backups)
                except OSError as exc:
                    print(f"midgard-farm-service: known-good copy verification failed or publication was unavailable: {exc}",
                          file=sys.stderr)
            return 0

        print(f"midgard-farm-service: farmer did not finish cleanly (exit {code} phase={phase or ''} "
              f"reason={reason or ''} failed={bool(failed)})", file=sys.stderr)
        exit_code = status.get("exit_code")
        result = exit_code if type(exit_code) is int and 0 < exit_code <= 255 else code
        return result if result not in (0, 78) else 1
