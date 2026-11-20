"""A fake process that speaks the farmer's filesystem and test-hook protocols."""

import json
import os
import sys
import time
from pathlib import Path

from fake_smoke_game import CATALOG
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
catalog_evidence = {}
verify_oaths = os.environ.get("FARMER_TEST_OATHS") == "1"
verify_wishlist = os.environ.get("FARMER_TEST_WISHLIST") == "1"
wishlist_evidence = []
oath_costs = {"tough": [1, 2, 4], "elite": [2, 4, 6], "hunt": [1, 2, 3], "mvp_fury": [2, 4]}


def difficulty():
    return 30 if verify_oaths and cfg.get("danger") == "auto" else cfg.get("danger")


def oath_points():
    return sum(oath_costs[key][rank - 1] for key, rank in cfg.get("oaths", {}).items())


def totals():
    return {"started": started, "runs": runs, "lost": lost, "zeny": zeny, "wins": runs}


def status(phase, reason="", code=0, detail=""):
    global seq
    seq += 1
    data = {"phase": phase, "session": session, "run_id": run_id, "heartbeat_seq": seq, "heartbeat": time.time(),
            "pid": os.getpid(), "terminal": phase in ("done", "failed"), "failed": phase == "failed",
            "finish_reason": reason, "exit_code": code, "last_transition": "transition",
            "profile": {"zeny": int(save.read_text())}, "totals": totals(), "last": last}
    data["target"] = {"stage": cfg.get("stage"), "danger": difficulty(), "class": cfg.get("class"),
                      "oath_points": oath_points() if phase != "failed" else 0}
    if detail:
        data["last_error"] = detail
    if phase == "done" and os.environ.get("FARMER_TEST_PREPARATION") == "1":
        assert all(cfg[key] for key in ("auto_upgrades", "auto_sage", "auto_fuse", "auto_achievements",
                                       "auto_potential", "auto_storage_prune", "potential_max_rolls"))
        before = {"loadouts": {"swordsman": {"weapon": "worn"}}, "potentials": {"worn": {"tier": 1}},
                  "pet": "poring", "album": ["poring_card"], "stats": {"swordsman": {"str": 1}},
                  "rebirths": {}, "rebirth_levels": {"swordsman": 0}, "free_points": 2,
                  "pick_order": {"swordsman": ["bash"]}, "pick_limits": {}}
        after = before | {"free_points": 3}
        if fault == "rerolled-worn-item":
            after["potentials"] = {"worn": {"tier": 2}}
        if fault == "no-free-points":
            before["free_points"] = 0
        data["preparation"] = {"before": before, "after": after}
    if phase == "done" and catalog_evidence:
        data["catalog_evidence"] = catalog_evidence
    if phase == "done" and verify_oaths:
        saved = {"curse": 1}
        data["oath_evidence"] = {"before": saved, "after": {} if fault == "changed-saved-oaths" else saved}
    if phase == "done" and verify_wishlist:
        data["wishlist_evidence"] = wishlist_evidence
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


def settle_wishlist(row):
    expensive, wanted, unwanted = ("sacred_excalibur", "gungnir", "legendary_shield")
    skips = [{"id": expensive, "reason": "over_zeny_limit"}]
    if started == 1:
        row["kept"] = [wanted]
        before = {"stored_ids": [], "legend_coins": 0, "zeny": 100000}
        after = {"stored_ids": [wanted], "legend_coins": 4, "zeny": 85000}
    else:
        skips.append({"id": wanted, "reason": "already_owned"})
        before = {"stored_ids": [wanted], "legend_coins": 4, "zeny": 85000}
        after = {"stored_ids": [wanted], "legend_coins": 9, "zeny": 85000}
        if fault == "duplicate-wishlist-item":
            after["stored_ids"].append(wanted)
    if fault == "no-wishlist-cash-in":
        after["legend_coins"] = before["legend_coins"]
    for skip in skips:
        log(f"KEEP_SKIP {skip['id']} reason={skip['reason']}")
    row.update(victory=False, keep_skipped=skips)
    wishlist_evidence.append({
        "fixture_ids": [expensive, wanted, unwanted], "wishlist": [expensive, wanted], "free": False,
        "offer": [{"id": item, "cost": cost, "legend_coins": coins, "sell_zeny": 0}
                  for item, cost, coins in ((expensive, 25000, 3), (wanted, 15000, 1), (unwanted, 15000, 1))],
        "before": before, "after": after,
    })


def settle(force, *, wait_at_keep=False):
    row = {"session": session, "run_id": run_id, "zeny_gain": 20, "kills": 15, "game_s": 7, "victory": True,
           "endless": cfg.get("endless"), "endless_mvps": 3, "kept": [], "force_reason": force,
           "forced": os.environ.get("FARMER_TEST_FREEZE_RUN_TIME") == "1" and fault != "unforced-stall"}
    row.update(stage=cfg.get("stage"), danger=difficulty(), oath_points=oath_points())
    if fault == "wrong-oath-journal-points":
        row["oath_points"] = 0
    if fault == "wrong-run-journal-target":
        row["danger"] = 29
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
    if verify_wishlist:
        settle_wishlist(row)
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
if cfg.get("stage") == "not-a-location":
    status("failed", "invalid_location", 1, "" if fault == "no-choice-diagnostic" else "Location 'not-a-location' is unknown.")
    sys.exit(1)
if cfg.get("danger") == 31:
    status("failed", "invalid_difficulty", 1, "Difficulty 31 is outside the allowed range.")
    sys.exit(1)
if ranks := cfg.get("oaths"):
    detail = ""
    if cfg["danger"] != 30:
        detail = "Oaths require fixed difficulty 30."
    else:
        for name, rank in ranks.items():
            if name not in oath_costs:
                detail = f"Unknown oath '{name}'."
                break
            if rank > len(oath_costs[name]):
                detail = f"Oath '{name}' has no rank {rank}."
                break
    if detail:
        status("failed", "invalid_oath", 1, detail)
        sys.exit(1)
if os.environ.get("FARMER_TEST_CATALOG") == "1":
    catalog_evidence = {
        "before_run": CATALOG["written_at"] + 1,
        "unlocked_max_difficulty": 4,
        "location_prerequisites": {"prontera": "", "payon": "prontera"},
        "cleared_locations": {},
        "oath_points": {"tough": [1]},
        "legendary_ids": ["sacred_excalibur"],
        "stored_ids": ["sacred_excalibur", "sacred_excalibur"],
    }
    if fault != "no-catalog":
        payload = CATALOG | ({"locations": []} if fault == "empty-locations" else {})
        os_.write_atomic(profile / "farmer_catalog.json", json.dumps(payload).encode())
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
deadline = time.monotonic() + 0.65 if cfg.get("run_minutes") == 0.2 else 0
if started == 1:
    while time.monotonic() < deadline:
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
                action = command()
                if action == "resume_settings":
                    cfg = json.loads((profile / "farmer.cfg").read_bytes())
                    break
                if action == "resume":
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
if os.environ.get("FARMER_TEST_FREEZE_RUN_TIME") == "1":
    for tries in (1, 2, 3):
        log(f"RUN_STALL clock={tries * 5.0:.1f} t=12.0 tries={tries}")
if os.environ.get("FARMER_TEST_FLUSH_FAIL") == "1":
    log("FAIL flush_failed")
    status("failed", "flush_failed", 1)
    sys.exit(1)
settle("run_timeout")
if verify_wishlist:
    started += 1
    run_id = f"{session}-r{started}"
    settle("run_timeout")
if cfg.get("endless"):
    log("ENDLESS_DONE goal")
if cfg.get("class") == "thief":
    log("STOP max_minutes")
finish("max_runs" if cfg["max_runs"] else "max_minutes")
