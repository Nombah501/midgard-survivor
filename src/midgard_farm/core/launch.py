"""One launch attempt; the service owns the outcome and any retry policy."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from ..platform import LockHeld, NetworkIsolationError, Platform
from .backup import backup_directory, publish_known_good, snapshot_profile
from .commands import Character
from .preflight import check_prerequisites, preflight

SHUTDOWN_GRACE_SECONDS = 45  # Match the legacy supervisor's stop_grace.
_SETTLED_REASONS = frozenset({"finish", "stop", "max_runs", "wins", "goal", "no_target"})


class GameBusy(Exception):
    """Another launcher or game instance is active (exit 1)."""


@contextmanager
def shutdown_request() -> Iterator[Callable[[], float | None]]:
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


def _read_status(os_: Platform, profile: Path, session_id: str | None, *,
                 retry_missing: bool = False) -> dict | None:
    try:
        status = json.loads(os_.read_shared(profile / "farmer_status.json", retry_missing=retry_missing))
    except (OSError, ValueError):
        return None
    if isinstance(status, dict) and (session_id is None or status.get("session") == session_id):
        if session_id is None:
            # Standalone launch also accepts older phase-only status files.
            status.setdefault("terminal", status.get("phase") in ("done", "failed"))
        return status
    return None


def request_finish(profile: Path) -> None:
    try:
        (profile / "farmer_stop").touch()
    except OSError as exc:
        print(f"midgard-farm-service: could not write farmer_stop: {exc}", file=sys.stderr)


@dataclass(frozen=True)
class AttemptExit:
    code: int
    status: dict | None
    last_status: dict | None
    forced_reason: str | None

    @property
    def normalized_code(self) -> int:
        return self.code if self.code >= 0 else 128 - self.code

    def clean(self, os_: Platform) -> bool:
        status = self.status or {}
        # A verified headless Linux finish SIGKILLs itself. Windows has no
        # reliable hard-exit code, but both OSes require the farmer's status.
        return (self.forced_reason is None and status.get("phase") == "done"
                and status.get("terminal") is True and not status.get("failed")
                and (not os_.game_exit_status_reliable or self.normalized_code in (0, 137)))


def _select_character(config_bytes: bytes, character: Character) -> bytes:
    config = json.loads(config_bytes)
    cid, branch = character.class_id, character.job_path
    config["class"] = cid
    config["job_paths"] = {cid: branch}
    # In Godot, builds.class and an explicit build job path take precedence.
    builds = config.get("builds")
    if isinstance(builds, dict):
        builds.pop("class", None)
        if isinstance(build := builds.get(cid), dict) and "job_path" in build:
            build["job_path"] = branch
    return json.dumps(config, indent=2).encode()


def run_attempt(
    os_: Platform, profile: Path, preset: Path | None, session_id: str | None, *,
    take_service_lock: bool = False, character: Character | None = None,
    log_path: Path | None = None, watch: Callable[[dict | None], str | None] | None = None,
    poll_interval: float = 0.05,
) -> AttemptExit:
    """Run one attempt; a watcher may return a reason to force-stop its tree."""
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
        config = plan.config
        if character is not None:
            assert config is not None, "character selection requires a preset"
            config = _select_character(config, character)
        if config is not None:
            os_.write_atomic(profile / "farmer.cfg", config)
        (profile / "farmer_stop").unlink(missing_ok=True)
        (profile / "farmer_status.json").unlink(missing_ok=True)
        if watch is not None:
            (profile / "farmer_command").unlink(missing_ok=True)
            (profile / "farmer_command.claimed").unlink(missing_ok=True)
        farmer_log = profile / "farmer.log"
        if farmer_log.is_file():
            os_.replace_atomic(farmer_log, profile / "farmer.log.prev")

        if log_path is None:
            log_dir = os_.app_data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=log_dir, prefix="run-", suffix=".log", delete=False) as temporary:
                log_path = Path(temporary.name)
        env = {**os.environ, "FARMER_SESSION": "1"}
        if session_id:
            env["FARMER_SESSION_ID"] = session_id
        else:
            env.pop("FARMER_SESSION_ID", None)
        # The CLI tees stdout; the background service keeps output in the attempt log.
        shutdown = shutdown_request() if watch is None else nullcontext(lambda: None)
        with (
            log_path.open("wb") as log,
            log_path.open("rb") if watch is None else nullcontext() as output,
            shutdown as shutdown_requested_at,
        ):
            def tee() -> None:
                if output is not None:
                    while chunk := output.read(65536):
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()

            stop_sent = False
            forced_reason = None
            last_status = None
            expected_session = session_id if watch is not None else None
            try:
                with os_.spawn_tree(plan.argv, cwd=Path(plan.argv[0]).parent, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, isolate_network=bool(session_id)) as tree:
                    while True:
                        tee()
                        timeout = poll_interval
                        if (requested_at := shutdown_requested_at()) is not None:
                            if not stop_sent:
                                request_finish(profile)
                                stop_sent = True
                            timeout = min(timeout, max(0.0, requested_at + SHUTDOWN_GRACE_SECONDS - time.monotonic()))
                        try:
                            code = tree.wait(timeout=timeout)
                            break
                        except subprocess.TimeoutExpired:
                            if watch is not None:
                                status = _read_status(os_, profile, expected_session)
                                if status is not None:
                                    last_status = status
                                forced_reason = watch(status)
                            elif timeout == 0:
                                forced_reason = "operator_timeout"
                            if forced_reason:
                                tree.kill()
                                code = tree.wait()
                                break
            except NetworkIsolationError as exc:
                tee()
                raise NetworkIsolationError(f"{exc}; see {log_path}") from exc
            else:
                tee()

        status = _read_status(os_, profile, expected_session, retry_missing=True)
        result = AttemptExit(code, status, status if status is not None else last_status, forced_reason)
        reason = (status or {}).get("finish_reason")
        if session_id and result.clean(os_) and isinstance(reason, str) and reason in _SETTLED_REASONS:
            try:
                publish_known_good(os_, profile, backups)
            except OSError as exc:
                print(f"midgard-farm-service: known-good copy verification failed or publication was unavailable: {exc}",
                      file=sys.stderr)
        return result
