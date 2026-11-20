"""Background service entry point: one instance per user, bound to the profile."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from pathlib import Path

from . import assets, platform
from .core import app_update
from .core.commands import Resume, Start, submit
from .core.config import read_config
from .core.game_update import START_GAME_AND_UPDATE
from .core.launch import GameBusy, run_attempt, shutdown_request
from .core.notify import Notifier
from .core.preflight import PreflightError
from .core.profile import AmbiguousProfile, ProfileNotFound, find_profile
from .core.state import StateKind, StateReporter
from .core.supervisor import InvalidSavedSession, Policy, Supervisor, log, pending_commands, refuse_command
from .platform._systemd import render_unit

# sysexits: the same "unfixable" code run.sh's preflight uses.
EX_TEMPFAIL = 75
EX_CONFIG = 78
EXIT_QUARANTINE = 2


def service_command(*, windowless: bool) -> list[str]:
    """Resolve the service entry point for the checkout or a frozen bundle."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    executable = Path(sys.executable)
    if windowless:
        executable = executable.with_name("pythonw.exe")
        if not executable.is_file():
            raise RuntimeError(f"windowless Python interpreter not found at {executable}")
    return [str(executable), "-m", "midgard_farm.service"]


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
    updater = app_update.AppUpdater(os_, assets.version(), notifier.notify)
    with lock, shutdown_request() as requested_at, StateReporter(os_) as state, updater:
        try:
            if app_update.recover_on_start(os_, updater.version):
                return 0
        except (OSError, RuntimeError, subprocess.SubprocessError):
            log("could not resume pending App update watchdog")
            return 1

        def before_start() -> bool:
            for path, command in pending_commands(os_, state):
                if command != "rollback_app":
                    continue
                queued, reason = updater.begin(manual=True)
                if queued:
                    path.unlink()
                    state.set(StateKind.UPDATING, "Rolling back the app")
                    return True
                if reason:
                    refuse_command(os_, state, path, "rollback_app", reason)
            queued, _ = updater.begin(manual=False)
            if queued:
                state.set(StateKind.UPDATING, "Installing an App update")
            return queued
        last_missing = ""
        while requested_at() is None:
            try:
                profile = find_profile(os_.godot_user_data_root())
            except ProfileNotFound as exc:
                os_.game_running()  # Windows learns its install path even before the profile exists.
                reason = str(exc)
                guidance = reason if isinstance(exc, AmbiguousProfile) else START_GAME_AND_UPDATE
                if reason != last_missing:
                    last_missing = reason
                    state.set(StateKind.FARMER_UNAVAILABLE, guidance)
                    log(f"profile not found: {reason}")
                for path, command in pending_commands(os_, state):
                    if isinstance(command, Start):
                        refuse_command(os_, state, path, "start", guidance)
                    elif isinstance(command, Resume):
                        refuse_command(os_, state, path, "resume", guidance)
                    elif command in ("check_again", "restore_official", "rollback_app"):
                        refuse_command(os_, state, path, command, guidance)
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
            try:
                if not app_update.report_ready(os_, updater.version, lambda: requested_at() is not None):
                    return 0
            except (OSError, RuntimeError, ValueError) as exc:
                log(f"App update startup checks failed: {type(exc).__name__}")
                return 1
            app_update.flush_history(os_)
            updater.start()
            log(f"profile: {profile}")
            supervisor = Supervisor(os_, profile, policy, requested_at, notifier.notify, state=state,
                                    before_start=before_start)
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


def main(argv: Sequence[str] | None = None, *, policy: Policy = Policy()) -> int:
    platform.run_isolation_helper()
    # Redirected output on Windows defaults to the ANSI code page, which
    # cannot encode every profile path.
    # The scheduled action (pythonw or a windowed frozen binary) has neither stream.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__)
    registration = parser.add_mutually_exclusive_group()
    registration.add_argument("--register", action="store_true", help="register the background service for this user")
    registration.add_argument("--unregister", action="store_true", help="remove the service registration")
    registration.add_argument("--print-unit", action="store_true", help="render the systemd user unit")
    registration.add_argument("--print-task", action="store_true", help="render the Windows Task Scheduler XML")
    registration.add_argument("--app-update-handoff", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help="render the service definition without registering it")
    subcommands = parser.add_subparsers(dest="command")
    launch = subcommands.add_parser("launch", help="launch one attempt with the installed farmer patch")
    launch.add_argument("preset", nargs="?", type=Path, help="JSON preset; defaults to the profile's farmer.cfg")
    launch.add_argument("--session-id", default=os.environ.get("FARMER_SESSION_ID"),
                        help="run a supervised attempt (defaults to FARMER_SESSION_ID)")
    subcommands.add_parser("rollback-app", help="request rollback to the previous app version")
    args = parser.parse_args(argv)
    if args.command and any((args.register, args.unregister, args.print_unit, args.print_task, args.dry_run,
                             args.app_update_handoff)):
        parser.error("service registration options cannot be combined with launch")
    if args.dry_run and args.unregister:
        parser.error("--dry-run cannot be combined with --unregister")
    if args.print_unit:
        print(render_unit(service_command(windowless=False)), end="")
        return 0
    os_ = platform.current()
    windows = os_.release_os == "windows"
    if args.print_task and not windows:
        parser.error("--print-task is only available on Windows")

    if args.register or args.unregister or args.dry_run or args.print_task:
        try:
            if args.unregister:
                os_.unregister_service()
            else:
                argv = service_command(windowless=windows)
                if args.dry_run or args.print_task:
                    print(os_.render_service(argv), end="")
                else:
                    os_.register_service(argv)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else None
            print(f"midgard-farm-service: {str(detail or exc).strip()}", file=sys.stderr)
            return 1
        return 0
    if args.command == "rollback-app":
        try:
            submit(os_, "rollback_app")
        except OSError as exc:
            print(f"midgard-farm-service: could not queue App rollback: {exc}", file=sys.stderr)
            return 1
        return 0
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
        if args.app_update_handoff:
            def deliver_update_notification(event: str, message: str) -> None:
                notifier.notify(event, message)
                notifier.drain(timeout=10)

            return app_update.run_watchdog(os_, args.app_update_handoff, deliver_update_notification)
        return _serve(os_, policy, notifier)
    finally:
        notifier.drain()


if __name__ == "__main__":
    sys.exit(main())
