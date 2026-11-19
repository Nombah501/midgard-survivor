"""Background service entry point: one instance per user, bound to the profile."""

import argparse
import json
import os
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from . import platform
from .core.launch import GameBusy, run_attempt, shutdown_request
from .core.preflight import PreflightError
from .core.profile import ProfileNotFound, find_profile
from .core.supervisor import InvalidSavedSession, Policy, Supervisor, log

# sysexits: the same "unfixable" code run.sh's preflight uses.
EX_TEMPFAIL = 75
EX_CONFIG = 78
EXIT_QUARANTINE = 2

UNIT = """\
[Unit]
Description=Midgard Farm background service
StartLimitIntervalSec=1h
StartLimitBurst=3

[Service]
Type=simple
ExecStart={exec_start}
EnvironmentFile=-%h/.config/midgard-farmer.env
Restart=on-failure
RestartSec=30
RestartPreventExitStatus=2 75
# Signal only the service first so it can ask the game to finish and flush.
KillMode=mixed
TimeoutStopSec=90

[Install]
WantedBy=default.target
"""


def _systemd_quote(arg: str) -> str:
    arg = arg.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return '"' + arg.replace("%", "%%").replace("$", "$$") + '"'


class _Notifier:
    def __init__(self, ntfy_url: str):
        self.url = ntfy_url
        self.pending: list[threading.Thread] = []

    def _send(self, title: str, message: str) -> None:
        try:
            request = urllib.request.Request(self.url, data=message.encode(), headers={"Title": title})
            urllib.request.urlopen(request, timeout=10).close()
        except (OSError, ValueError) as exc:
            log(f"ntfy failed: {exc}")

    def notify(self, event: str, message: str) -> None:
        log(f"notify {event}: {message}")
        if self.url:
            self.pending = [thread for thread in self.pending if thread.is_alive()]
            thread = threading.Thread(target=self._send, args=(f"Midgard farmer: {event}", message), daemon=True)
            thread.start()
            self.pending.append(thread)

    def drain(self) -> None:
        deadline = time.monotonic() + 25
        for thread in self.pending:
            thread.join(max(0.0, deadline - time.monotonic()))


def _startup_quarantine(os_: platform.Platform, data: Path, notifier: _Notifier,
                        reason: str, description: str, error: Exception,
                        *, saved_session: Path | None = None) -> int:
    detail = f"{description}: {error}"
    notifier.notify("quarantine", detail)
    record: dict[str, object] = {"reason": reason, "detail": detail, "attempts": []}
    try:
        if saved_session is not None:
            diagnostics = Path("logs") / f"startup-quarantine-{uuid.uuid4().hex}"
            directory = data / diagnostics
            directory.mkdir(parents=True)
            record["diagnostics"] = diagnostics.as_posix()
            os_.write_atomic(directory / "quarantine.json", json.dumps(record, indent=2).encode())
        os_.write_atomic(data / "quarantine.json", json.dumps(record, indent=2).encode())
        if saved_session is not None:
            os_.replace_atomic(saved_session, directory / saved_session.name)
            return 0
    except OSError as exc:
        log(f"could not preserve startup quarantine diagnostics: {exc}")
    return EXIT_QUARANTINE


def _serve(os_: platform.Platform, policy: Policy, notifier: _Notifier) -> int:
    data = os_.app_data_dir()
    lock_path = data / "service.lock"
    try:
        data.mkdir(parents=True, exist_ok=True)
        lock = os_.acquire_lock(lock_path)
    except platform.LockHeld:
        print(f"supervisor: another supervisor is already running (lock {lock_path})", file=sys.stderr)
        return EX_TEMPFAIL
    except OSError as exc:
        return _startup_quarantine(os_, data, notifier, "app_data_unusable", "app data directory unusable", exc)
    with lock, shutdown_request() as requested_at:
        last_missing = ""
        while requested_at() is None:
            try:
                profile = find_profile(os_.godot_user_data_root())
            except ProfileNotFound as exc:
                if str(exc) != last_missing:
                    last_missing = str(exc)
                    log(f"profile not found: {exc}")
                time.sleep(1)
            except OSError as exc:
                return _startup_quarantine(os_, data, notifier, "profile_unusable", "profile directory unusable", exc)
            else:
                break
        else:
            return 0
        try:
            # Also honor the legacy supervisor's profile lock until cutover.
            profile_lock = os_.acquire_lock(profile / "farmer_supervisor.lock")
        except platform.LockHeld:
            print(f"supervisor: another supervisor is already running for {profile}", file=sys.stderr)
            return EX_TEMPFAIL
        except OSError as exc:
            return _startup_quarantine(os_, data, notifier, "profile_unusable", "profile directory unusable", exc)
        with profile_lock:
            log(f"profile: {profile}")
            supervisor = Supervisor(os_, profile, policy, requested_at, notifier.notify)
            try:
                supervisor.run()
            except InvalidSavedSession as exc:
                result = _startup_quarantine(os_, data, notifier, "invalid_saved_session",
                                             "saved AFK session unusable", exc, saved_session=supervisor.session_path)
                if result != 0:
                    return result
                supervisor.run()
    return 0


def main(*, policy: Policy = Policy()) -> int:
    platform.run_isolation_helper()
    # Redirected output on Windows defaults to the ANSI code page, which
    # cannot encode every profile path.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-unit", action="store_true", help="print the systemd user unit without installing it")
    parser.add_argument("--ntfy-url", default=os.environ.get("FARMER_NTFY_URL", ""))
    subcommands = parser.add_subparsers(dest="command")
    launch = subcommands.add_parser("launch", help="launch one attempt with the installed farmer patch")
    launch.add_argument("preset", nargs="?", type=Path, help="JSON preset; defaults to the profile's farmer.cfg")
    launch.add_argument("--session-id", default=os.environ.get("FARMER_SESSION_ID"),
                        help="run a supervised attempt (defaults to FARMER_SESSION_ID)")
    args = parser.parse_args()
    if args.print_unit:
        argv = [sys.executable]
        if not getattr(sys, "frozen", False):
            argv.extend(("-m", "midgard_farm.service"))
        print(UNIT.format(exec_start=" ".join(map(_systemd_quote, argv))), end="")
        return 0

    os_ = platform.current()
    if args.command == "launch":
        try:
            profile = find_profile(os_.godot_user_data_root())
            result = run_attempt(os_, profile, args.preset, args.session_id, take_service_lock=True)
            status = result.status or {}
            code = result.normalized_code
            reason = status.get("finish_reason") or ""
            if result.clean(os_):
                print(f"farmer: finished cleanly (exit {code} reason={reason})")
                return 0
            print(f"midgard-farm-service: farmer did not finish cleanly (exit {code} "
                  f"phase={status.get('phase') or ''} reason={reason} failed={bool(status.get('failed'))})",
                  file=sys.stderr)
            exit_code = status.get("exit_code")
            code = exit_code if type(exit_code) is int and 0 < exit_code <= 255 else code
            return code if code not in (0, EX_CONFIG) else 1
        except (ProfileNotFound, PreflightError, platform.NetworkIsolationError) as exc:
            print(f"midgard-farm-service: {exc}", file=sys.stderr)
            return EX_CONFIG
        except (GameBusy, OSError) as exc:
            if isinstance(exc, BrokenPipeError):
                # Discard the unwritten buffer on interpreter shutdown, too.
                with open(os.devnull, "wb") as sink:
                    os.dup2(sink.fileno(), sys.stdout.fileno())
            print(f"midgard-farm-service: {exc}", file=sys.stderr)
            return 1

    notifier = _Notifier(args.ntfy_url)
    try:
        return _serve(os_, policy, notifier)
    finally:
        notifier.drain()


if __name__ == "__main__":
    sys.exit(main())
