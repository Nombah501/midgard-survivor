"""A fake process that speaks the farmer's filesystem and test-hook protocols."""

import json
import os
import sys
import time
from pathlib import Path
from random import Random

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
assert cfg["display"] is (os.environ.get("FAKE_VERIFY_WATCH_MODE") == "1")
assert sys.argv[1:] == ([] if cfg["display"] else ["--headless"])
valkyrie_drill = os.environ.get("FARMER_TEST_VALKYRIE") == "1"
hel_route_drill = os.environ.get("FARMER_TEST_EARLY_MVP") == "1"
field_navigation = os.environ.get("FARMER_TEST_FIELD_NAVIGATION") == "1"
field_charge = os.environ.get("FARMER_TEST_FIELD_CHARGE") == "1"
mvp_drill = os.environ.get("FARMER_TEST_MVP_MECHANICS") == "1"
verify_progress = os.environ.get("FARMER_TEST_PROGRESS") == "1"
verify_tower_parity = os.environ.get("FARMER_TEST_TOWER_PARITY") == "1"
verify_tower_run = os.environ.get("FARMER_TEST_TOWER_RUN") == "1"
verify_tower_crash = os.environ.get("FARMER_TEST_TOWER_CRASH") == "1"
tower_evidence = {}
tower_intent = {}
if field_navigation:
    assert cfg["altar_policy"] == "map-wide"
elif hel_route_drill:
    assert cfg["karma_route"] == "hel"
elif cfg.get("run_minutes") != 50 and not verify_progress:
    assert cfg.get("altar_policy", "cautious") in ("cautious", "map-wide")
    assert cfg.get("karma_route", "natural") in ("natural", "valhalla", "hel", "rotate")
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
oath_costs = {"tough": [1, 2, 4], "elite": [2, 4, 6], "hunt": [1, 2, 3], "kyrie": [1, 2, 3],
              "mvp_fury": [2, 4], "hellfire": [1, 2, 3], "lex": [2, 4], "curse": [2, 4], "unlucky": [3, 6]}
hell_rotation = cfg.get("run_minutes") == 50 and not (valkyrie_drill or field_charge or mvp_drill)
rotation_index = None
rotation_locations = [
    {"id": "prontera", "name": "Prontera Field", "unlocked": True, "min_difficulty": 1, "max_difficulty": 30},
    {"id": "payon", "name": "Payon Forest", "unlocked": False, "min_difficulty": 2, "max_difficulty": 30},
    {"id": "orc", "name": "Orc Village", "unlocked": True, "min_difficulty": 5, "max_difficulty": 30},
]


def rotating():
    return cfg.get("stage") == {"mode": "rotation"}


def advance_rotation():
    global rotation_index
    if rotating():
        if rotation_index is None:
            rotation_index = Random(int(os.environ.get("FAKE_VERIFY_ROTATION_SEED", "0"))).randrange(2)
            selection = "fixed" if fault == "unlogged-random-start" else "random"
            log(f"ROTATION_START stage={rotation_location()['id']} selection={selection}")
        else:
            rotation_index = (rotation_index + 1) % 2


def rotation_location():
    return [rotation_locations[0], rotation_locations[2]][rotation_index]


def location():
    return rotation_location()["id"] if rotating() and rotation_index is not None else cfg.get("stage")


def publish_rotation_catalog():
    data = CATALOG | {"locations": rotation_locations, "unlocked_max_difficulty": 30}
    os_.write_atomic(profile / "farmer_catalog.json", json.dumps(data).encode())


def difficulty():
    if rotating() and cfg.get("danger") == "auto":
        return rotation_location()["min_difficulty"]
    return 30 if verify_oaths and cfg.get("danger") == "auto" else cfg.get("danger")


def oath_points():
    return sum(oath_costs[key][rank - 1] for key, rank in cfg.get("oaths", {}).items())


def totals():
    return {"started": started, "runs": runs, "lost": lost, "zeny": zeny,
            "wins": 0 if verify_tower_run else runs, "coins": 0, "ymir": 0}


def status(phase, reason="", code=0, detail=""):
    global seq
    seq += 1
    data = {"phase": phase, "session": session, "run_id": run_id, "heartbeat_seq": seq, "heartbeat": time.time(),
            "pid": os.getpid(), "terminal": phase in ("done", "failed"), "failed": phase == "failed",
            "finish_reason": reason, "exit_code": code, "last_transition": "transition",
            "profile": {"zeny": int(save.read_text())}, "totals": totals(), "last": last}
    data["target"] = {"stage": location(), "danger": difficulty(), "class": cfg.get("class"),
                      "oath_points": oath_points() if phase != "failed" else 0}
    data["game"] = {"stage": location(), "danger": difficulty()}
    if detail:
        data["last_error"] = detail
    if phase == "done" and os.environ.get("FARMER_TEST_PREPARATION") == "1":
        assert all(cfg[key] for key in ("auto_upgrades", "auto_sage", "auto_fuse", "auto_achievements",
                                       "auto_potential", "auto_storage_prune", "potential_max_rolls"))
        before = {"loadouts": {"swordsman": {"weapon": "worn"}}, "potentials": {"worn": {"tier": 1}},
                  "pet": "poring", "album": ["poring_card"], "stats": {"swordsman": {"str": 1}},
                  "rebirths": {}, "rebirth_levels": {"swordsman": 0}, "free_points": 2,
                  "pick_order": {"swordsman": ["bash"]}, "pick_limits": {}, "pick_fill": True,
                  "pick_bans": {"swordsman": ["skill:magnum_break"]}, "endless_auto_pick": True}
        after = before | {"free_points": 3}
        if fault == "rerolled-worn-item":
            after["potentials"] = {"worn": {"tier": 2}}
        if fault == "no-free-points":
            before["free_points"] = 0
        if fault == "reset-saved-auto-pick":
            after["endless_auto_pick"] = False
        if fault != "no-native-auto-pick":
            print("AUTOPICK t=4.0 lv=2 pick=skill:bash Nv 2", flush=True)
        data["preparation"] = {"before": before, "after": after}
    if phase == "done" and catalog_evidence:
        data["catalog_evidence"] = catalog_evidence
    if phase == "done" and verify_oaths:
        saved = {"curse": 1}
        data["oath_evidence"] = {"before": saved, "after": {} if fault == "changed-saved-oaths" else saved}
    if phase == "done" and verify_wishlist:
        data["wishlist_evidence"] = wishlist_evidence
    if phase == "done" and verify_progress:
        data["run_id"] = ""  # Recovery finished with a last run, not an active one.
        after = last["progress"]["after"].copy()
        if fault == "replayed-native-progress":
            after["history"] = [after["history"][0], *after["history"][:49]]
        data["progress_saved"] = after
    if tower_evidence and (phase == "done" or verify_tower_crash):
        data["tower_evidence"] = tower_evidence
    if fault == "no-transition":
        del data["last_transition"]
    if fault == "pause-starts-run" and phase == "paused" and seq > 2:
        data["totals"]["started"] += 1
    os_.write_atomic(profile / "farmer_status.json", json.dumps(data).encode())


def log(message):
    with (profile / "farmer.log").open("a", encoding="utf-8") as fp:
        print(f"FARMER 2026-01-01T00:00:00 {message}", file=fp, flush=True)


def checkpoint(phase, row=None):
    payload = {"phase": phase, "session": session, "run_id": run_id, "totals": totals(), "row": row,
               "rotation_index": rotation_index}
    if tower_intent:
        payload["tower_intent"] = tower_intent
    os_.write_atomic(checkpoint_path, json.dumps(payload).encode())


def crash(point):
    if hook == point and not crashed.exists():
        crashed.write_text(point)
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
    expensive, wanted, other = ("sacred_excalibur", "gungnir", "legendary_shield")
    keep_unowned = cfg["keep_unowned_legendaries"]
    skips = [{"id": expensive, "reason": "over_zeny_limit"}]
    before = {"stored_ids": [], "legend_coins": 0, "zeny": 200000}
    if wishlist_evidence:
        before = wishlist_evidence[-1]["after"]
    kept = [wanted] if started == 1 else [other] if started == 2 and keep_unowned else []
    if started > 1:
        skips.append({"id": wanted, "reason": "already_owned"})
    if keep_unowned and started != 2:
        skips.append({"id": other, "reason": "no_keep_slots" if started == 1 else "already_owned"})
    if fault == "ignored-wishlist-priority" and started == 1:
        kept = [other]
    row["kept"] = kept
    after = {"stored_ids": before["stored_ids"] + kept,
             "legend_coins": before["legend_coins"] + 5 - len(kept),
             "zeny": before["zeny"] - 15000 * len(kept)}
    if fault == "duplicate-wishlist-item" and started == 2:
        after["stored_ids"].append(wanted)
    if fault == "no-wishlist-cash-in":
        after["legend_coins"] = before["legend_coins"]
    for skip in skips:
        log(f"KEEP_SKIP {skip['id']} reason={skip['reason']}")
    row.update(victory=False, keep_skipped=skips)
    offer = [(expensive, 50000, 3), (wanted, 15000, 1), (other, 15000, 1)]
    if keep_unowned:
        offer.insert(0, offer.pop())
    wishlist_evidence.append({
        "fixture_ids": [expensive, wanted, other], "wishlist": [expensive, wanted], "free": False,
        "offer": [{"id": item, "cost": cost, "legend_coins": coins, "sell_zeny": 0}
                  for item, cost, coins in offer],
        "before": before, "after": after,
    })


def hell_evidence(row):
    row.update(run_mvps=4 if fault == "uncounted-finale-mvp" else 5,
               endless_mvps=2, valkyrie_kills=2, reginleif_cards_gain=1)
    if fault != "no-altars":
        log("ALTAR_TAKE id=freyja from=26.5 nearby=12 t=90.0 raid=idle ref=1")
    if fault == "took-hel":
        log("ALTAR_TAKE id=hel from=25.0 nearby=11 t=120.0 raid=idle ref=2")
    else:
        log("ALTAR_SKIP id=hel reason=hel t=120.0 raid=idle ref=2")
    skip_raid = "portal" if fault == "wrong-baldur-skip" else "idle"
    take_raid = "idle" if fault == "baldur-in-field" else "portal"
    log(f"ALTAR_SKIP id=baldur reason=baldur_waits_portal t=440.0 raid={skip_raid} ref=3")
    log(f"ALTAR_TAKE id=baldur from=8.0 nearby=0 t=480.0 raid={take_raid} ref=3")
    log("ALTAR_SKIP id=thor reason=channel_interrupted t=520.0 raid=idle ref=4")
    if fault == "interrupted-altar-taken":
        log("ALTAR_TAKE id=thor from=8.0 nearby=0 t=521.0 raid=idle ref=4")
    for n, mvp in enumerate((1, 3), 1):
        if n == 2 and fault == "missing-mvp-log":
            break
        log(f"BOSS_WON t={n * 480:.1f} mvps={mvp} wall_ms=10")
        if not (n == 2 and fault == "no-second-route"):
            log(f"KARMA_ROUTE side=light mvp=reginleif after_mvp={mvp} t={n * 480:.1f}")
        kill = f"VALKYRIE_KILLED mvp=reginleif after_mvp={mvp} boons={n} t={n * 480:.1f}"
        if n == 1 or fault not in {"no-second-valkyrie", "late-valkyrie"}:
            log(kill)
        log(f"ENDLESS_START time={n * 480:.1f} n={n}")
        if n == 2 and fault == "late-valkyrie":
            log(kill)


def hel_evidence(row):
    route = "KARMA_ROUTE side=dark mvp=randgris_fallen after_mvp=1 t=92.0 revives=3 falls=0 doom=false"
    if fault == "early-hel-route":
        log(route)
    log("BOSS_WON t=91.0 mvps=1 wall_ms=10")
    if fault != "early-hel-route":
        log(route)
    if fault != "no-randgris-kill":
        boon = "none" if fault == "no-hel-pact" else "hel_pact"
        log(f"RANDGRIS_KILLED mvp=randgris_fallen after_mvp=1 boons=1 t=92.0 revives=3 falls=0 boon={boon}")
    row.update(karma_side="dark", randgris_kills=1, randgris_fallen_cards_gain=0, run_mvps=2,
               arena_timings=[] if fault == "no-randgris-journal" else [
                   {"kind": "randgris", "boss": "randgris_fallen", "kill_ms": 30},
               ], died=fault == "hel-death")


def settle_progress(row):
    row.update(game_s=510, **{"class": "thief"})
    entry = {key: row[key] for key in ("class", "stage", "danger", "victory")} | {"mvps": 1, "time": 510}
    before = {
        "history": [{"at": index} for index in range(50)], "altars": 23, "altars_run": 0, "oath_best": {},
        "hell_maps": {}, "hell_classes": {}, "titles": {}, "cloud_rev": 5, "world_feats": [],
    }
    after = before | {
        "history": [entry, *before["history"][:49]], "altars": 26, "altars_run": 3, "oath_best": {"prontera": 37},
        "hell_maps": {"prontera": True}, "hell_classes": {"thief": True}, "titles": {"hell_15": True, "oath_max": True},
    }
    row["progress"] = {
        "run_id": run_id, "before": before, "after": after, "altar_takes": 3, "mvps": 1, "net_mode": "",
        "board_requests": int(fault == "native-progress-online"),
    }



def tower_fixture(id_, level, *, farmer=False, locked=False, xp=0.0, saved_at=1.0):
    return {"id": id_, "class": "thief", "job": "Assassin", "level": level, "farmer": farmer, "locked": locked,
            "xp_progress": xp, "saved_at": saved_at, "digest": f"{id_}-content"}


def publish_tower_catalog(snapshots):
    data = CATALOG | {"tower": {"open": True, "hel_unlocked": False, "hel_reason": "Clear floor 100 first.",
                               "checkpoints": [1], "snapshots": [
                                   {k: v for k, v in snap.items() if k != "digest"} | {"index": i}
                                   for i, snap in enumerate(snapshots)
                               ]}}
    os_.write_atomic(profile / "farmer_catalog.json", json.dumps(data).encode())


def settle_tower_parity(row):
    assert cfg["danger"] == 30
    manual = tower_evidence.setdefault("before", [
        tower_fixture(f"manual-{i}", 20 + i, locked=i == 0) for i in range(10)
    ])
    row["player_level"] = 20 if started == 1 else 25
    saved = tower_fixture(f"farmer-{started}", row["player_level"], farmer=True)
    if fault == "kept-old-farmer-snapshot" and started == 2:
        saved = tower_evidence["1"][-1]
    if fault == "evicted-manual-snapshot":
        manual = manual[1:]
    builds = [*manual, saved]
    tower_evidence[str(started)] = builds
    publish_tower_catalog(builds)


def settle_tower_run(row):
    floor = cfg["stage"]["floor"]
    assert cfg["stage"]["kind"] == "normal" and cfg["max_runs"] == 0
    snapshot = tower_evidence["before"][-1]
    row.update(stage="tower", danger=25, victory=False, finale_won=False, died=False, forced=True,
               tower_floor_start=floor + (fault == "tower-wrong-floor"), tower_floor_best=floor + 1,
               end_cause="finish", snapshot={key: snapshot[key] for key in ("id", "level", "job")})
    before = {"loadouts": {"thief": {"weapon": "worn"}}, "potentials": {"worn": {"tier": 1}}, "pet": "poring"}
    after = before | {"pet": "pupa"} if fault == "tower-preparation-changed" else before
    tower_evidence.update(after=tower_evidence["before"][: -2 if fault == "tower-spent-two" else -1],
                          preparation_before=before, preparation_after=after, autopilot_at_end=True,
                          board_requests=int(fault == "tower-online"))
    publish_tower_catalog(tower_evidence["after"])


def settle(force, *, wait_at_keep=False):
    row = {"session": session, "run_id": run_id, "zeny_gain": 20, "kills": 15, "game_s": 7, "victory": True,
           "endless": cfg.get("endless"), "endless_mvps": 3, "kept": [], "force_reason": force,
           "forced": os.environ.get("FARMER_TEST_FREEZE_RUN_TIME") == "1" and fault != "unforced-stall",
           "falls_by_mechanic": {"Golpe aplastante": 1} if fault == "mvp-fall" else {}}
    row.update(stage=location(), danger=difficulty(), oath_points=oath_points())
    if hel_route_drill:
        hel_evidence(row)
    if hell_rotation:
        assert cfg["objective"] == "crumbs" and cfg["class"] == "thief" and cfg["job_paths"] == {"thief": 0}
        assert cfg["danger"] == 30
        assert cfg["endless"] and cfg["endless_minutes"] == cfg["endless_mvps"] == 0
        assert cfg["altar_policy"] == "map-wide" and cfg["karma_route"] == "valhalla"
        hell_evidence(row)
        row.update(game_s=2451, job="stalker" if fault == "wrong-job" else "assassin_cross",
                   finale_won=fault not in {"no-victory", "no-finale"})
        if fault == "forced-finale":
            row.update(forced=True, force_reason="run_timeout")
    if fault == "wrong-oath-journal-points":
        row["oath_points"] = 0
    if fault == "wrong-run-journal-target":
        row["danger"] = 29
    if fault == "locked-rotation-location" and started == 2:
        row["stage"] = "payon"
    if fault == "no-victory":
        row["victory"] = False
        if hell_rotation:
            row.update(died=True, game_s=1842)
            log("PLAYER_DIED t=1842.0 by=Orc Warrior what=Bash")
    if fault == "no-mvp":
        row["endless_mvps"] = 0
    if not (fault == "unbanked-zeny" and started == 2):
        save.write_text(str(int(save.read_text()) + 20))
    log("SETTLE rewards")
    if os.environ.get("FARMER_TEST_FLUSH_FAIL") == "keep":
        print("ERROR: Save: cannot write the keep profile", file=sys.stderr, flush=True)
        log("FAIL flush_failed")
        status("failed", "flush_failed", 1, "Could not verify the profile save at keep.")
        sys.exit(1)
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
    if verify_progress:
        settle_progress(row)
    if verify_tower_parity:
        settle_tower_parity(row)
    if verify_tower_run:
        settle_tower_run(row)
    if hell_rotation:
        keep = "free=false slots=1" if fault == "paid-finale-keep" else "free=true slots=3"
        log(f"KEEP_DONE kept=0 offer=0 victory={str(row['victory']).lower()} {keep}")
    else:
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
if rotating():
    publish_rotation_catalog()
    if cfg["danger"] == 1:
        status("failed", "invalid_difficulty", 1, "Difficulty 1 is outside the allowed range for location 'orc'.")
        sys.exit(1)
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
    if saved["session"] == session and saved["phase"] == "tower_intent":
        run_id = saved["run_id"]
        if fault == "tower-crash-restart-write":
            save.write_text("1")
        log("FAIL tower_intent_unresolved")
        status("failed", "tower_intent_unresolved", 1)
        sys.exit(1)
    if saved["session"] == session:
        started, run_id = saved["totals"]["started"], saved["run_id"]
        rotation_index = saved.get("rotation_index")
    else:
        saved = {}
    if saved.get("phase") == "run":
        lost = 1
        log("RUN_LOST before settlement")
    elif saved.get("phase") == "settled":
        row = saved["row"]
        if journal_path.exists():
            log("RECOVER journal=present")
        else:
            append(row)
            log("RECOVER journal=appended")
        if fault == "duplicate-journal":
            append(row)
        account(row)
        if verify_progress:
            finish("max_runs")

started += 1
advance_rotation()
run_id = f"{session}-r{started}"
if verify_tower_run or verify_tower_crash:
    tower_evidence["before"] = [
        tower_fixture("locked", 99, locked=True),
        tower_fixture("same-level-lower-xp", 30, xp=0.1, saved_at=40.0),
        tower_fixture("same-level-same-xp-older", 30, xp=0.2, saved_at=10.0),
        tower_fixture("selected", 30, xp=0.2, saved_at=20.0),
    ]
    tower_intent = {"snapshot_id": "selected", "run_id": run_id}
    checkpoint("tower_intent")
    if verify_tower_crash:
        snapshots = tower_evidence["before"]
        remaining = snapshots
        if hook == "tower_started":
            remaining = snapshots[: -2 if fault == "tower-crash-double-spend" else -1]
            save.write_text(str(boot_zeny - (len(snapshots) - len(remaining))))
        profile_evidence = {"preparation": {"pet": "poring"}, "other_sha256": "same"}
        tower_evidence.update(before_crash=profile_evidence | {"snapshots": snapshots},
                              at_crash=profile_evidence | {"snapshots": remaining}, board_requests=0)
        status("idle")
        crash(hook)
    log(f"TOWER_START run={run_id} kind=normal floor={cfg['stage']['floor']} snapshot=selected")
checkpoint("run")
crash("run")
status("run")
if verify_tower_run:
    log(f"TOWER_FLOOR cleared={cfg['stage']['floor'] + 1}")
    os_.write_atomic(profile / "farmer_command", b"finish\n")
    assert command() == "finish"
    settle("finish")
    finish("tower_finished")
deadline = time.monotonic() + 0.65 if cfg.get("run_minutes") == 0.2 else 0
# A scripted Pause must be delivered before this run settles; the verifier owns the timeout.
wait_for_pause = os.environ.get("FAKE_VERIFY_PAUSE_AFTER_RUNS") == str(runs)
if started == 1 or wait_for_pause:
    while wait_for_pause or time.monotonic() < deadline:
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
                    if rotating():
                        publish_rotation_catalog()
                    break
                if action == "resume":
                    break
                time.sleep(0.04)
            started += 1
            advance_rotation()
            run_id = f"{session}-r{started}"
            status("run")
            time.sleep(0.07)  # Leave time to observe the new run.
            settle("run_timeout")
            while rotating() and runs < cfg["max_runs"]:
                started += 1
                advance_rotation()
                run_id = f"{session}-r{started}"
                settle("run_timeout")
            finish("max_runs")
        if os.environ.get("FARMER_TEST_WAIT_AT_KEEP") == "1":
            time.sleep(0.07)
            settle("run_timeout", wait_at_keep=True)
        time.sleep(0.02)
if os.environ.get("FARMER_TEST_BLOCKED_PORTAL") == "1":
    log("BLOCKED_PORTAL seeded")
    if fault != "portal-not-entered":
        log("BLOCKED_PORTAL entered")
if field_navigation:
    log("FIELD_NAVIGATION seeded")
    if fault != "altar-expired-instead":
        log("ALTAR_SKIP id=freyja reason=expires_first")
    log("ALTAR_TAKE id=loki from=16.0")
    if fault != "maze-stall":
        log("FIELD_NAVIGATION collected")
    if fault != "pocket-stall":
        log("FIELD_NAVIGATION escaped")
if os.environ.get("FARMER_TEST_FREEZE_RUN_TIME") == "1":
    for tries in (1, 2, 3):
        log(f"RUN_STALL clock={tries * 5.0:.1f} t=12.0 tries={tries}")
if field_charge:
    for started in range(1, cfg["max_runs"] + 1):
        run_id = f"{session}-r{started}"
        contacts = int(fault == "charge-contact" and started == 1)
        log(f"FIELD_CHARGE run={started} contacts={contacts} falls=0 died=false")
        settle("")
    finish("max_runs")
if valkyrie_drill:
    moves = "spear spears pillars starfall judgment aegis einherjar seals charge scales".split()
    for started, ability in enumerate(moves + ["starfall"] * (cfg["max_runs"] - len(moves)), 1):
        run_id = f"{session}-r{started}"
        meteor_hit = int(fault == "meteor-hit" and started == 4)
        contacts = max(meteor_hit, int(fault == "meteor-contact" and started == 4))
        marks = (5 if fault == "meteor-incomplete" and started == 4 else 6) if ability == "starfall" else 0
        log(f"VALKYRIE_DRILL run={started} ability={ability} danger={difficulty()} oaths={oath_points()} "
            f"marks={marks} contacts={contacts} hits={meteor_hit} died=false cause=")
        settle("")
    finish("max_runs")
if mvp_drill:
    trials = cfg["max_runs"] // 3
    for started, ability in enumerate(["spears"] * trials + ["quake"] * trials + ["slam"] * trials, 1):
        run_id = f"{session}-r{started}"
        hits = int(fault == "mvp-contact" and started == 1)
        strikes = 2 if ability == "spears" and fault != "mvp-incomplete" else 1
        log(f"MVP_DRILL run={started} ability={ability} danger={difficulty()} oaths={oath_points()} "
            f"strikes={strikes} contacts={hits} hits=0 died=false")
        settle("")
    finish("max_runs")
settle("" if hell_rotation or hel_route_drill else "run_timeout")
while (rotating() or verify_wishlist or verify_tower_parity) and runs < cfg["max_runs"]:
    started += 1
    advance_rotation()
    run_id = f"{session}-r{started}"
    settle("run_timeout")
if cfg.get("endless") and not hell_rotation:
    log("ENDLESS_DONE goal")
if cfg.get("class") == "thief":
    log("STOP max_minutes")
finish("max_runs" if cfg["max_runs"] else "max_minutes")
