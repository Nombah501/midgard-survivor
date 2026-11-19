"""Instrument the existing fake GDRE and smoke game at their process boundaries."""

import json
import os
import sys
from pathlib import Path

import fake_gdre
import fake_smoke_game


def record(stage):
    patches = Path(os.environ["FAKE_SMOKE_PROFILE"]) / "patches"
    state = (patches / "state.json").read_text(encoding="utf-8")
    snapshot = patches / "official-state.json"
    with open(os.environ["FAKE_UPDATE_TRACE"], "a", encoding="utf-8") as log:
        print(json.dumps({"stage": stage, "state": state,
                          "snapshot": snapshot.read_text(encoding="utf-8") if snapshot.exists() else None}), file=log)


def reopen_after(stage):
    if os.environ.get("FAKE_UPDATE_REOPEN") == stage:
        Path(os.environ["FAKE_UPDATE_RUNNING"]).touch()


if __name__ == "__main__":
    tool = sys.argv.pop(1)
    if tool == "gdre":
        if sys.argv[2].startswith("--extract=") and sys.argv[-1] == "--include=res://scripts/autoload/save.gdc":
            if Path(sys.argv[2].split("=", 1)[1]).name != "patch_farmer.pck":
                record("build")
        fake_gdre.main()
        if sys.argv[2].startswith("--pck-patch="):
            reopen_after("build")
    elif tool == "smoke":
        record("smoke")
        fake_smoke_game.main()
        reopen_after("smoke")
    else:
        sys.exit(f"Unexpected fake tool: {tool}")
