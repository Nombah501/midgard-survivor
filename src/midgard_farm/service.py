"""Background service entry point: one instance per user, bound to the profile."""

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

from . import platform
from .core.commands import Start
from .core.config import read_config
from .core.launch import GameBusy, run_attempt, shutdown_request
from .core.notify import Notifier
from .core.preflight import PreflightError
from .core.profile import ProfileNotFound, find_profile
from .core.state import StateKind, StateReporter
from .core.supervisor import InvalidSavedSession, Policy, Supervisor, log, pending_commands, refuse_start

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


def _startup_quarantine(os_: platform.Platform, data: Path, notifier: Notifier,
                        reason: str, description: str, error: Exception,
                        *, state: StateReporter | None = None, saved_session: Path | None = None) -> int:
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
        if state is not None:
            kind = StateKind.IDLE if saved_session is not None else StateKind.FARMER_UNAVAILABLE
            state.set(kind, detail, quarantine=record)
        if saved_session is not None:
            os_.replace_atomic(saved_session, directory / saved_session.name)
            return 0
    except OSError as exc:
        log(f"could not preserve startup quarantine diagnostics: {exc}")
    return EXIT_QUARANTINE


def _serve(os_: platform.Platform, policy: Policy, notifier: Notifier) -> int:
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
    with lock, shutdown_request() as requested_at, StateReporter(os_) as state:
        last_missing = ""
        while requested_at() is None:
            try:
                profile = find_profile(os_.godot_user_data_root())
            except ProfileNotFound as exc:
                reason = str(exc)
                if reason != last_missing:
                    last_missing = reason
                    state.set(StateKind.FARMER_UNAVAILABLE, reason)
                    log(f"profile not found: {reason}")
                for path, command in pending_commands(os_):
                    if isinstance(command, Start):
                        refuse_start(os_, state, path, reason)
                    else:
                        path.unlink()
                time.sleep(1)
            except OSError as exc:
                return _startup_quarantine(os_, data, notifier, "profile_unusable", "profile directory unusable", exc,
                                           state=state)
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
            return _startup_quarantine(os_, data, notifier, "profile_unusable", "profile directory unusable", exc,
                                       state=state)
        with profile_lock:
            if last_missing:
                state.set(StateKind.IDLE)
            log(f"profile: {profile}")
            supervisor = Supervisor(os_, profile, policy, requested_at, notifier.notify, state=state)
            try:
                supervisor.run()
            except InvalidSavedSession as exc:
                result = _startup_quarantine(os_, data, notifier, "invalid_saved_session",
                                             "saved AFK session unusable", exc, state=state,
                                             saved_session=supervisor.session_path)
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

    notifier = Notifier(os_, read_config(os_).ntfy_url)
    try:
        return _serve(os_, policy, notifier)
    finally:
        notifier.drain()


if __name__ == "__main__":
    sys.exit(main())
