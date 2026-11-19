"""Fake smoke game: use the child's Godot environment and emit game artifacts."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from midgard_farm import platform


def main():
    real = Path(os.environ["FAKE_SMOKE_PROFILE"])
    profile = platform.current().godot_user_data_root() / real.name
    assert not profile.samefile(real), "refusing to play on the source profile"
    patches = profile / "patches"
    records = Path(os.environ["FAKE_SMOKE_RECORDS"])
    attempt = len(list(records.glob("attempt-*.json")))
    mode = json.loads(os.environ.get("FAKE_SMOKE_MODES", '["pass"]'))[attempt]
    record = {
        "profile": str(profile),
        "original_save": (profile / "profile.json").read_text(encoding="utf-8"),
        "mounted": json.loads((patches / "state.json").read_text(encoding="utf-8")),
        "candidate": (patches / "patch_farmer.pck").read_text(encoding="utf-8"),
        "official_linked": (patches / "official.pck").samefile(real / "patches/official.pck"),
        "bridge_linked": (patches / "bridge.pck").samefile(real / "patches/bridge.pck"),
        "config": json.loads((profile / "farmer.cfg").read_text(encoding="utf-8")),
        "args": sys.argv[1:],
        "farmer_enabled": os.environ.get("FARMER_SESSION"),
        "stale_files": sorted(p.name for p in profile.glob("farmer*") if p.name != "farmer.cfg"),
    }
    if sys.platform == "linux":
        record["netns"] = os.readlink("/proc/self/ns/net")
        record["interfaces"] = [name for _, name in socket.if_nameindex()]
    (records / f"attempt-{attempt + 1}.json").write_text(json.dumps(record), encoding="utf-8")
    (profile / "profile.json").write_text("sandbox played", encoding="utf-8")
    status = {
        "phase": "done", "terminal": True, "failed": False,
        "totals": {"wins": 1, "runs": 1},
        "last": {"victory": True, "kills": 50, "zeny_gain": 25},
    }
    if mode == "not_done":
        status["phase"] = "run"
    elif mode == "failed":
        status["failed"] = True
    elif mode == "falsey_failed":
        status["failed"] = 0
    elif mode in {"no_wins", "remove_candidate"}:
        status["totals"]["wins"] = 0
        if mode == "remove_candidate":
            Path(os.environ["FAKE_SMOKE_CANDIDATE"]).unlink()
    elif mode == "defeat":
        status["last"]["victory"] = False
    elif mode == "no_kills":
        status["last"]["kills"] = 0
    elif mode == "no_zeny":
        status["last"]["zeny_gain"] = 0
    if mode != "no_status":
        raw = "[" if mode == "invalid_status" else json.dumps(status)
        (profile / "farmer_status.json").write_text(raw, encoding="utf-8")
    (profile / "farmer_runs.jsonl").write_text(json.dumps(status["last"]) + "\n", encoding="utf-8")
    marker = "NOT_FINISH" if mode == "no_finish" else "FINISH"
    (profile / "farmer.log").write_text(f"FARMER 2026-01-01T00:00:00 {marker} max_runs\n", encoding="utf-8")
    (profile / "logs").mkdir(exist_ok=True)
    (profile / "logs/godot.log").write_text("SCRIPT ERROR: not process output\n", encoding="utf-8")
    print("fake stdout", flush=True)
    print("fake stderr", file=sys.stderr, flush=True)
    if mode.startswith("output:"):
        print(mode.removeprefix("output:"), file=sys.stderr, flush=True)
    if mode == "bad_exit":
        sys.exit(42)
    if mode == "hang":
        subprocess.Popen([sys.executable, __file__, "--hold-lock", str(records)])
        time.sleep(60)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--hold-lock"]:
        folder = Path(sys.argv[2])
        with platform.current().acquire_lock(folder / "grandchild.lock"):
            (folder / "grandchild.ready").touch()
            time.sleep(60)
        sys.exit(0)
    main()
