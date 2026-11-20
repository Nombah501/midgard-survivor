"""Fake game's heartbeat, terminal status and Godot command mailbox."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from midgard_farm import platform

os_ = platform.current()
profile = Path(os.environ["FAKE_GAME_PROFILE"])
plan = Path(os.environ["FAKE_SUPERVISED_PLAN"])
count = plan.with_suffix(".count")
n = int(count.read_text()) if count.exists() else 0
count.write_text(str(n + 1))
steps = plan.read_text().splitlines()
kind, _, arg = steps[min(n, len(steps) - 1)].partition(":")
status_path = profile / "farmer_status.json"
stop = profile / "farmer_stop"
command_path = profile / "farmer_command"
seq = 0


def write_status(text):
    tmp = status_path.with_suffix(".tmp")
    tmp.write_text(text)
    os_.replace_atomic(tmp, status_path)


def status(phase="run", reason=""):
    global seq
    seq += 1
    data = {"phase": phase, "terminal": phase in {"done", "failed"},
            "failed": phase == "failed", "finish_reason": reason,
            "heartbeat_seq": seq, "pid": os.getpid(), "session": os.environ["FARMER_SESSION_ID"]}
    data["heartbeat"] = time.time()
    if kind == "commands":
        data["game"] = {"time": seq if arg == "endless" else 640, "in_raid": arg == "raid"}
        if arg == "clock-reset" and seq > 6:
            data["game"]["time"] = seq - 6
        if arg == "endless":
            data["run"] = {"endless_started_at": 300}
    if kind == "commands" and arg == "summary":
        data["totals"] = {"started": 2, "runs": 1, "wins": 1, "losses": 0, "lost": 1,
                          "zeny": 7200, "xp": 50, "kills": 40, "coins": 3, "ymir": 2}
    if phase == "done" and kind == "missing-terminal":
        del data["terminal"]
    if phase == "done" and kind == "foreign-session":
        data["session"] = "a different AFK session"
    write_status(json.dumps(data))


def forever():
    while True:
        time.sleep(1)


if kind == "exit":
    if arg == "78" and os.environ.get("FAKE_PREFLIGHT_DETAIL"):
        print("run: " + os.environ["FAKE_PREFLIGHT_DETAIL"], file=sys.stderr, flush=True)
    os._exit(int(arg))
if kind == "no-heartbeat":
    forever()
if kind == "commands" and arg == "preboot":
    plan.with_suffix(".preboot").touch()
    while not stop.exists():
        time.sleep(0.01)
    stop.unlink()
for _ in range(3):
    status()
    time.sleep(0.05)
if kind in {"clean", "missing-terminal", "foreign-session"}:
    status("done", arg)
    os._exit(0)
if kind == "done-bad-exit":
    status("done", arg)
    os._exit(9)
if kind == "done-sigkill":
    status("done", arg)
    os.kill(os.getpid(), signal.SIGKILL)
if kind == "fail":
    status("failed", arg)
    os._exit(1)
if kind == "crash":
    os._exit(1)
if kind == "garbage":
    write_status('{"phase":"done", "terminal')
    os._exit(0)
if kind == "hang":
    python = str(Path(sys.base_prefix) / "python.exe") if sys.platform == "win32" else sys.executable
    child = subprocess.Popen([python, "-c", "import time; time.sleep(300)"])
    plan.with_suffix(".grandchild").write_text(str(child.pid))
    forever()
if kind == "commands":
    phase = arg.removeprefix("phase-") if arg.startswith("phase-") else "run"
    deadline = time.monotonic() + 2 if arg == "timed-stall" else None
    while True:
        command = ""
        try:
            claimed = profile / "farmer_command.claimed"
            os_.replace_atomic(command_path, claimed)
            command = claimed.read_text().strip()
            claimed.unlink()
        except FileNotFoundError:
            pass
        if stop.exists():
            stop.unlink()
            if command != "abort":
                command = "finish"
        if command in ("finish", "abort"):
            if arg == "delay-terminal":
                for _ in range(5):
                    status("settle")
                    time.sleep(0.05)
            if arg == "summary":
                session = os.environ["FARMER_SESSION_ID"]
                with (profile / "farmer_runs.jsonl").open("a", encoding="utf-8") as journal:
                    for owner, wall_s in [("unrelated", 900), (session, 1800)]:
                        print(json.dumps({"session": owner, "run_id": owner + "-1", "wall_s": wall_s,
                                          "cards_gain": 2, "materials": {"ore": 4}, "victory": True}), file=journal)
            status("done", command)
            if arg == "no-exit":
                forever()
            os._exit(0)
        if command == "pause":
            phase = "paused"
        elif command == "resume":
            phase = "run"
        if deadline is not None and time.monotonic() >= deadline:
            status("done", "fixture_deadline")
            os._exit(0)
        status(phase)
        time.sleep(0.05)
raise RuntimeError(f"unknown fake game plan: {kind}:{arg}")
