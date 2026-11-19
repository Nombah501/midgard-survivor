#!/usr/bin/env python3
"""Fake farmer child for supervisor tests.

Usage: fake_farmer.py STATUS_PATH PLAN_FILE

PLAN_FILE holds one behaviour per line; attempt N plays line N (the last line
repeats). The attempt counter lives next to the plan file. Behaviours:

  clean:<reason>   heartbeat, write phase=done, exit 0
  fail:<reason>    heartbeat, write phase=failed, exit 1
  crash            heartbeat, exit 1 without a terminal status
  hang             heartbeat once, spawn a grandchild, then stop beating
  exit:<code>      exit with <code> before any status
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

status_path = Path(sys.argv[1])
plan_path = Path(sys.argv[2])
counter = plan_path.with_suffix(".count")

plan = plan_path.read_text().split()
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
step = plan[min(n, len(plan) - 1)]
kind, _, arg = step.partition(":")
seq = 0


def write(phase="run", failed=False, reason=""):
    global seq
    seq += 1
    data = {
        "phase": phase,
        "terminal": phase in ("done", "failed"),
        "failed": failed,
        "finish_reason": reason,
        "heartbeat_seq": seq,
        "pid": os.getpid(),
    }
    tmp = status_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(status_path)


def beat(times=3):
    for _ in range(times):
        write()
        time.sleep(0.05)


if kind == "exit":
    sys.exit(int(arg))
beat()
if kind == "clean":
    write("done", reason=arg)
    sys.exit(0)
if kind == "fail":
    write("failed", failed=True, reason=arg)
    sys.exit(1)
if kind == "crash":
    sys.exit(1)
if kind == "hang":
    child = subprocess.Popen(["sleep", "300"])
    plan_path.with_suffix(".grandchild").write_text(str(child.pid))
    while True:
        time.sleep(1)
sys.exit(f"unknown plan step: {step}")
