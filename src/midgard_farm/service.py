"""Background service entry point: one instance per user, bound to the profile."""

import argparse
import os
import sys
from pathlib import Path

from . import platform
from .core.launch import GameBusy, run_attempt
from .core.preflight import PreflightError
from .core.profile import ProfileNotFound, find_profile

# sysexits: the same "unfixable" code run.sh's preflight uses.
EX_TEMPFAIL = 75
EX_CONFIG = 78


def main() -> int:
    platform.run_isolation_helper()
    # Redirected output on Windows defaults to the ANSI code page, which
    # cannot encode every profile path.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command")
    launch = subcommands.add_parser("launch", help="launch one attempt with the installed farmer patch")
    launch.add_argument("preset", nargs="?", type=Path, help="JSON preset; defaults to the profile's farmer.cfg")
    launch.add_argument("--session-id", default=os.environ.get("FARMER_SESSION_ID"),
                        help="run a supervised attempt (defaults to FARMER_SESSION_ID)")
    args = parser.parse_args()

    os_ = platform.current()
    if args.command == "launch":
        try:
            profile = find_profile(os_.godot_user_data_root())
            return run_attempt(os_, profile, args.preset, args.session_id, take_service_lock=True)
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

    data = os_.app_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    try:
        lock = os_.acquire_lock(data / "service.lock")
    except platform.LockHeld:
        print(f"midgard-farm-service: already running (lock {data / 'service.lock'})", file=sys.stderr)
        return EX_TEMPFAIL
    with lock:
        try:
            profile = find_profile(os_.godot_user_data_root())
        except ProfileNotFound as exc:
            print(f"midgard-farm-service: {exc}", file=sys.stderr)
            return EX_CONFIG
        print(f"profile: {profile}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
