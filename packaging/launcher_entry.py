"""Service launcher: dispatch the current release from the per-user data directory."""

import sys

from midgard_farm import platform
from midgard_farm.core.install import launch_current

if __name__ == "__main__":
    raise SystemExit(launch_current(platform.current(), sys.argv[1:]))
