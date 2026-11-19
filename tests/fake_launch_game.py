"""Game stand-in copied to a temporary install by the launch tests."""

import json
import os
import resource
import signal
import socket
import sys
import time
from pathlib import Path

profile = Path(os.environ["FAKE_GAME_PROFILE"])
mode = os.environ.get("FAKE_GAME_MODE", "done")


record = {
    "netns": os.readlink("/proc/self/ns/net"),
    "interfaces": sorted(name for _, name in socket.if_nameindex()),
    "args": sys.argv[1:],
    "cwd": os.getcwd(),
    "session": os.environ.get("FARMER_SESSION"),
    "session_id": os.environ.get("FARMER_SESSION_ID"),
    "config": json.loads((profile / "farmer.cfg").read_text()),
}
ready = profile / "fake-game.json"
ready.with_suffix(".tmp").write_text(json.dumps(record))
ready.with_suffix(".tmp").replace(ready)
print("fake game stdout", flush=True)
print("fake game stderr", file=sys.stderr, flush=True)

if mode == "ignore-stop":
    signal.pause()
if mode == "finish-on-stop":
    while not (profile / "farmer_stop").exists():
        time.sleep(0.01)
    (profile / "profile.json").write_bytes(b"settled after shutdown request")
    mode = "done-137"
if mode == "large-profile":
    _, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    resource.setrlimit(resource.RLIMIT_FSIZE, (hard, hard))
    (profile / "profile.json").write_bytes(b"x" * 4096)
if mode in {"done", "done-137", "done-9", "large-profile"}:
    (profile / "farmer_status.json").write_text(json.dumps({
        "phase": "done",
        "failed": False,
        "finish_reason": os.environ.get("FAKE_GAME_FINISH_REASON", "max_runs"),
        "exit_code": 0,
    }))
if mode == "garbage":
    (profile / "farmer_status.json").write_text('{"phase": "done", "fail')
if mode in {"kill", "done-137"}:
    os.kill(os.getpid(), signal.SIGKILL)
raise SystemExit({"fail": 1, "done-9": 9}.get(mode, 0))
