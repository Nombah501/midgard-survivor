"""A fake process that speaks the farmer's filesystem and test-hook protocols."""

import json
import os
import sys
import time
from pathlib import Path

from midgard_farm import platform

os_ = platform.current()
source = Path(os.environ["FAKE_VERIFY_SOURCE"])
profile = os_.godot_user_data_root() / source.name
assert not profile.samefile(source), "refusing to play on the source profile"
assert os.environ["FARMER_SESSION"] == "1"
session = os.environ["FARMER_SESSION_ID"]
assert session.startswith("verify-")
cfg = json.loads((profile / "farmer.cfg").read_bytes())
assert not cfg["display"]
checkpoint_path = profile / "farmer_session.json"
journal_path = profile / "farmer_runs.jsonl"
save = profile / "profile.json"
fault = os.environ.get("FAKE_VERIFY_FAULT", "")
hook = os.environ.get("FARMER_TEST_CRASH_AT")
crashed = profile / "farmer_test_crashed"
boot_zeny = int(save.read_text())
seq = 0
started = runs = lost = zeny = 0
run_id = ""
last = {}


def totals():
    return {"started": started, "runs": runs, "lost": lost, "zeny": zeny, "wins": runs}


def status(phase, reason="", code=0):
    global seq
    seq += 1
    data = {"phase": phase, "session": session, "run_id": run_id, "heartbeat_seq": seq, "heartbeat": time.time(),
            "pid": os.getpid(), "terminal": phase in ("done", "failed"), "failed": phase == "failed",
            "finish_reason": reason, "exit_code": code, "last_transition": "transition",
            "profile": {"zeny": int(save.read_text())}, "totals": totals(), "last": last}
    if fault == "no-transition":
        del data["last_transition"]
    if fault == "pause-starts-run" and phase == "paused" and seq > 2:
        data["totals"]["started"] += 1
    os_.write_atomic(profile / "farmer_status.json", json.dumps(data).encode())


def log(message):
    with (profile / "farmer.log").open("a", encoding="utf-8") as fp:
        print(f"FARMER 2026-01-01T00:00:00 {message}", file=fp, flush=True)


def checkpoint(phase, row=None):
    payload = {"phase": phase, "session": session, "run_id": run_id, "totals": totals(), "row": row}
    os_.write_atomic(checkpoint_path, json.dumps(payload).encode())


def crash(point):
    if hook == point and not crashed.exists():
        crashed.touch()
        log(f"TEST_CRASH {point}")
        sys.exit(99)


def command():
    mailbox, claimed = profile / "farmer_command", profile / "farmer_command.claimed"
    if (profile / "farmer_stop").exists():
        (profile / "farmer_stop").unlink()
        return "finish"
    try:
        os_.replace_atomic(mailbox, claimed)
    except FileNotFoundError:
        return ""
    value = claimed.read_text().strip()
    claimed.unlink()
    return value


def append(row):
    with journal_path.open("a", encoding="utf-8") as file:
        print(json.dumps(row), file=file)


def account(row):
    global runs, zeny, last
    runs += 1
    zeny += row["zeny_gain"]
    last = row


def settle(force, *, wait_at_keep=False):
    row = {"session": session, "run_id": run_id, "zeny_gain": 20, "kills": 15, "game_s": 7, "victory": True,
           "endless": cfg.get("endless"), "endless_mvps": 3, "kept": [], "force_reason": force,
           "forced": os.environ.get("FARMER_TEST_FREEZE_RUN_TIME") == "1" and fault != "unforced-stall"}
    if fault == "no-victory":
        row["victory"] = False
    if fault == "no-mvp":
        row["endless_mvps"] = 0
    if not (fault == "unbanked-zeny" and started == 2):
        save.write_text(str(int(save.read_text()) + 20))
    log("SETTLE rewards")
    if wait_at_keep:
        while True:
            status("keep")
            if command() == "abort":
                if fault == "kept-on-abort":
                    row["kept"].append("an item")
                append(row)
                account(row)
                finish("abort")
            time.sleep(0.025)
    log("KEEP_DONE kept=0")
    checkpoint("settled", row)
    crash("settled")
    log("MAINT done")
    append(row)
    crash("journaled")
    account(row)
    checkpoint("idle")


def finish(reason):
    checkpoint("idle")
    log(f"FINISH {reason}")
    status("done", reason)
    if fault == "script-error":
        print("SCRIPT ERROR: fake error", file=sys.stderr, flush=True)
    sys.exit(0)


log(f"BOOT api=3 session={session} zeny={boot_zeny} cfg={json.dumps(cfg)}")
if fault == "hang":
    time.sleep(60)
if checkpoint_path.exists():
    try:
        saved = json.loads(checkpoint_path.read_bytes())
    except ValueError:
        if fault == "profile-mutated":
            save.write_text("0")
        log("FAIL checkpoint_corrupt")
        status("failed", "checkpoint_corrupt", 1)
        sys.exit(1)
    started, run_id = saved["totals"]["started"], saved["run_id"]
    if saved["phase"] == "run":
        lost = 1
        log("RUN_LOST before settlement")
    elif saved["phase"] == "settled":
        row = saved["row"]
        if journal_path.exists():
            log("RECOVER journal=present")
        else:
            append(row)
            log("RECOVER journal=appended")
        if fault == "duplicate-journal":
            append(row)
        account(row)

started += 1
run_id = f"{session}-r{started}"
checkpoint("run")
crash("run")
status("run")
if cfg.get("keep_on_defeat"):
    while True:
        control = command()
        if control == "abort":
            lost = 1
            finish("abort")
        if control == "finish":
            settle("finish")
            finish("finish")
        if control == "pause":
            settle("run_timeout")
            while True:
                status("paused")
                if command() == "resume":
                    break
                time.sleep(0.04)
            started += 1
            run_id = f"{session}-r{started}"
            status("run")
            time.sleep(0.07)  # Leave time to observe the new run.
            settle("run_timeout")
            finish("max_runs")
        if os.environ.get("FARMER_TEST_WAIT_AT_KEEP") == "1":
            time.sleep(0.07)
            settle("run_timeout", wait_at_keep=True)
        time.sleep(0.02)
if cfg.get("run_minutes") == 0.2 and started == 1:
    time.sleep(0.65)  # Leave time for the supervisor driver to see r1.
if os.environ.get("FARMER_TEST_FREEZE_RUN_TIME") == "1":
    for tries in (1, 2, 3):
        log(f"RUN_STALL clock={tries * 5.0:.1f} t=12.0 tries={tries}")
if os.environ.get("FARMER_TEST_FLUSH_FAIL") == "1":
    log("FAIL flush_failed")
    status("failed", "flush_failed", 1)
    sys.exit(1)
settle("run_timeout")
if cfg.get("endless"):
    log("ENDLESS_DONE goal")
if cfg.get("class") == "thief":
    log("STOP max_minutes")
finish("max_runs" if cfg["max_runs"] else "max_minutes")
