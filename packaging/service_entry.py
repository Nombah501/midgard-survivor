"""Service bootloader entry point and non-mutating packaged diagnostics."""

import json
import sys
from pathlib import Path

from midgard_farm import assets, platform, service
from midgard_farm.core.farmer_patch import farmer_hash


def self_check(report: Path) -> int:
    argv = service.service_command(windowless=sys.platform == "win32")
    report.write_text(json.dumps({
        "inputs": str(assets.farmer_inputs()),
        "farmer_hash": farmer_hash(),
        "version": assets.version(),
        "registration": platform.current().render_service(argv),
    }), encoding="utf-8")
    return 0


if __name__ == "__main__":
    # A windowless Windows bootloader has no stdout, so emit a file instead.
    if len(sys.argv) == 3 and sys.argv[1] == "--self-check":
        raise SystemExit(self_check(Path(sys.argv[2])))
    raise SystemExit(service.main())
