"""Install or uninstall the Midgard Farm release for the current user."""

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from . import assets, platform
from .core.farmer_patch import GameRunning, PatchStateError
from .core.install import SetupError, install, service_registration_command, uninstall
from .core.profile import ProfileNotFound


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--uninstall", action="store_true", help="remove the service and restore the official patch")
    action.add_argument("--print-registration", action="store_true", help="render the service definition without installing")
    args = parser.parse_args(argv)
    try:
        os_ = platform.current()
        if args.print_registration:
            print(os_.render_service(service_registration_command(os_)), end="")
        elif args.uninstall:
            uninstall(os_)
            print("Midgard Farm service removed. Profile, logs and history were kept.")
        else:
            if not getattr(sys, "frozen", False):
                raise SetupError("run midgard-farm-setup from an unpacked release archive")
            target = install(os_, Path(sys.executable).parent, assets.version())
            for warning in os_.setup_warnings():
                print(f"Warning: {warning}", file=sys.stderr)
            print(f"Midgard Farm installed. Open {target / ('midgard-farm' + os_.executable_suffix)}.")
    except platform.LockHeld:
        print("midgard-farm-setup: another service or legacy farmer is still running; stop it and retry",
              file=sys.stderr)
        return 1
    except (GameRunning, OSError, PatchStateError, ProfileNotFound, RuntimeError, SetupError,
            subprocess.SubprocessError) as exc:
        detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else None
        print(f"midgard-farm-setup: {str(detail or exc).strip()}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
