#!/usr/bin/env python3
"""Stand-in executable installed under the game's name by test_run_sh.py."""
import json
import os
import signal
import socket
import sys
from pathlib import Path


data = Path(os.environ["XDG_DATA_HOME"]) / "godot/app_userdata/Midgard Survivors"
mode = os.environ.get("RUNSH_FAKE_MODE", "done")
if mode == "wait":
    def finish(*_):
        (data / "fake-game.term").touch()
        raise SystemExit(42)

    signal.signal(signal.SIGTERM, finish)

record = {
    "netns": os.readlink("/proc/self/ns/net"),
    "interfaces": sorted(name for _, name in socket.if_nameindex()),
    "pgrp": os.getpgrp(),
}
tmp = data / "fake-game.tmp"
tmp.write_text(json.dumps(record))
tmp.replace(data / "fake-game.json")
print("fake game stdout", flush=True)
print("fake game stderr", file=sys.stderr, flush=True)

if mode == "wait":
    signal.pause()
if mode in {"done", "done-137", "done-9"}:
    (data / "farmer_status.json").write_text(
        json.dumps({
            "phase": "done",
            "failed": False,
            "finish_reason": os.environ.get("RUNSH_FAKE_FINISH_REASON", "max_runs"),
            "exit_code": 0,
        })
    )
if mode == "garbage":
    (data / "farmer_status.json").write_text('{"phase": "done", "fail')
if mode in {"kill", "done-137"}:
    os.kill(os.getpid(), signal.SIGKILL)
raise SystemExit({"done": 0, "done-9": 9, "fail": 1, "garbage": 0}.get(mode, 9))
