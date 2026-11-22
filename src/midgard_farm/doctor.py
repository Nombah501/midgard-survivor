"""Report local Midgard Farm diagnostics without making changes."""

import argparse
import sys
from collections.abc import Sequence

from . import platform
from .core.doctor import run_checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m midgard_farm.doctor", description=__doc__)
    parser.parse_args(argv)
    checks = run_checks(platform.current())
    for row in checks:
        print(f"{row['status'].upper()} [{row['id']}] {row['summary']}")
        if action := row["next_action"]:
            print(f"  Next: {action}")
    return int(any(row["status"] == "fail" for row in checks))


if __name__ == "__main__":
    # Redirected Windows output can use an ANSI code page unable to encode profile names.
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.exit(main())
