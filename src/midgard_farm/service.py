"""Background service entry point: one instance per user, bound to the profile."""

import sys

from . import platform
from .core.profile import ProfileNotFound, find_profile

# sysexits: the same "unfixable" code run.sh's preflight uses.
EX_TEMPFAIL = 75
EX_CONFIG = 78


def main() -> int:
    os_ = platform.current()
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
