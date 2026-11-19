#!/usr/bin/env python3
"""Run a real supervisor inside a verify.sh sandbox and drive one fault or sample it.

  drive_supervisor.py DATA_DIR MODE OUT_PREFIX -- SUPERVISOR_COMMAND...

MODE:
  kill-run  SIGKILL the game once while the status shows run r1 (before settlement)
  wait      only wait (in-farmer FARMER_TEST_* hooks inject the fault)
  sample    every 5 s append heartbeat, game RSS and disk usage to OUT_PREFIX.samples.jsonl

Exits with the supervisor's exit code; 3 when kill-run never found its moment.
SIGTERM/SIGINT are forwarded to the supervisor, which then finishes the farmer.
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

FARMER_DIR = Path(__file__).resolve().parent.parent
SAMPLE_EVERY = 5.0


def read_status(data):
    try:
        status = json.loads((data / "farmer_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return status if isinstance(status, dict) else {}


def rss_kb(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def disk_kb(roots, since):
    """Bytes under the sandbox plus farmer logs written during this drive, in KiB."""
    total = 0
    for root, only_new in roots:
        for path in root.rglob("*"):
            try:
                st = path.lstat()
            except OSError:
                continue
            if path.is_file() and not path.is_symlink() and (not only_new or st.st_mtime >= since):
                total += st.st_blocks * 512
    return total // 1024


def sample(data, sandbox, started):
    status = read_status(data)
    pid = status.get("pid")
    return json.dumps({
        "t": time.time(),
        "heartbeat_seq": status.get("heartbeat_seq"),
        "phase": status.get("phase"),
        "pid": pid,
        "rss_kb": rss_kb(pid) if pid else None,
        "disk_kb": disk_kb([(sandbox, False), (FARMER_DIR / "logs", True)], started),
    }) + "\n"


def main():
    data, mode, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    command = sys.argv[sys.argv.index("--") + 1:]
    sandbox = data.parents[2]  # <sandbox>/godot/app_userdata/<game>
    started = time.time()
    sup = subprocess.Popen(command)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sup.send_signal(signal.SIGTERM))
    killed = False
    next_sample = 0.0
    with open(f"{out}.samples.jsonl", "a", encoding="utf-8") as samples:
        while sup.poll() is None:
            status = read_status(data)
            if mode == "kill-run" and not killed and status.get("phase") == "run" \
                    and str(status.get("run_id", "")).endswith("-r1") and status.get("pid"):
                os.kill(int(status["pid"]), signal.SIGKILL)
                killed = True
                print(f"drive: SIGKILL game pid {status['pid']} in run {status['run_id']}", flush=True)
            if mode == "sample" and time.time() >= next_sample:
                next_sample = time.time() + SAMPLE_EVERY
                samples.write(sample(data, sandbox, started))
                samples.flush()
            time.sleep(0.05)
        if mode == "sample":
            samples.write(sample(data, sandbox, started))  # the soak's end, not the last tick
    code = sup.wait()
    if mode == "kill-run" and not killed:
        print("drive: the game never reached run r1; nothing was killed", flush=True)
        return 3
    return code


if __name__ == "__main__":
    sys.exit(main())
