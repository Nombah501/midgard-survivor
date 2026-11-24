"""Verify captured game evidence, not just process exit codes."""

import json
import re
from collections import Counter
from pathlib import Path

from ..core import smoke
from ..core.catalog import read_catalog
from ..core.history import read_history
from .drive import Driven, Run
from .soak import judge_files, read_jsonl

TOWER_CRASH_POINTS = ("tower_intent", "tower_started")


class VerificationFailure(Exception):
    pass


def need(condition: object, message: str) -> None:
    if not condition:
        raise VerificationFailure(message)


def _marker(run: Run, marker: str, *, suffix: str = "farmer.log") -> None:
    path = run.artifact(suffix)
    need(path.is_file(), "no farmer.log")
    need(marker in path.read_text(encoding="utf-8"), f"missing log marker: {marker}")


def _done(status: dict, *, needs_run: bool = True) -> None:
    need(status.get("phase") == "done", "phase != done")
    need(status.get("terminal"), "terminal false")
    need(not status.get("failed"), "failed true")
    need(status.get("finish_reason"), "finish_reason empty")
    need(status.get("last_transition"), "last_transition empty")
    need(int(status.get("heartbeat_seq") or 0) > 0, "heartbeat_seq == 0")
    need(status.get("run_id") or (status.get("last") or {}).get("run_id"), "run_id empty")
    if needs_run:
        need(int((status.get("totals") or {}).get("runs") or 0) >= 1, "runs == 0")


def _exit(driven: Driven, code: int = 0) -> None:
    need(driven.code == code, f"launch exit {driven.code} (expected {code})")


def one_run(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    reason = smoke.judge_one_run(run.os, run.profile, driven.outputs[0])
    need(not reason, reason)


def watch_mode(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    need(status["totals"]["runs"] == 1, "expected one completed run")
    outcome = driven.outcome or {}
    need(outcome.get("kind") == "finished" and outcome.get("reason") == "max_runs",
         "supervisor did not report a clean finish at the run limit")
    need(len(outcome.get("attempts", [])) == 1, "supervisor restarted the game")


def catalog(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    data = read_catalog(run.os, run.profile)
    if data is None:
        raise VerificationFailure("no valid catalog")
    evidence = status.get("catalog_evidence")
    if not evidence:
        raise VerificationFailure("no boot-time catalog evidence")
    need(data["written_at"] <= evidence["before_run"], "catalog was not written before the first run")
    need(data["unlocked_max_difficulty"] == evidence["unlocked_max_difficulty"], "wrong unlocked maximum difficulty")
    expected = {key: not prerequisite or bool(evidence["cleared_locations"].get(prerequisite))
                for key, prerequisite in evidence["location_prerequisites"].items()}
    locations = data["locations"]
    need(expected and len(locations) == len(expected)
         and {entry["id"]: entry["unlocked"] for entry in locations} == expected, "wrong location unlocks")
    for entry in locations:
        need(entry["name"] and 1 <= entry["min_difficulty"] <= entry["max_difficulty"] <= data["max_difficulty"],
             f"invalid location name or difficulty range: {entry['id']}")
    oaths = data["oaths"]
    need(oaths and len(oaths) == len(evidence["oath_points"])
         and {entry["id"]: [rank["points"] for rank in entry["ranks"]] for entry in oaths} == evidence["oath_points"],
         "wrong oath ranks or costs")
    for entry in oaths:
        need(entry["name"] and entry["description"] and entry["ranks"]
             and all(rank["rank"] == n and rank["description"] for n, rank in enumerate(entry["ranks"], 1)),
             f"missing oath name or rank descriptions: {entry['id']}")
    legendaries = data["legendaries"]
    need(legendaries and all(entry["name"] for entry in legendaries)
         and sorted(entry["id"] for entry in legendaries) == sorted(evidence["legendary_ids"]), "wrong legendaries")
    need(sorted(data["owned_item_ids"]) == sorted(set(evidence["stored_ids"])), "wrong owned item ids")


def preparation_unchanged(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    need(status["totals"]["runs"] == 1, "expected one completed run")
    need(status["last"]["game_s"] > 0, "the run did not advance")
    snapshots = status.get("preparation") or {}
    before, after = snapshots.get("before"), snapshots.get("after")
    if not before or not after:
        raise VerificationFailure("missing preparation snapshots")
    need(before["free_points"] > 0, "the starting character must have unspent stat points")
    need(before["potentials"], "the starting profile must have worn equipment")
    need(after["free_points"] >= before["free_points"], "unspent stat points decreased")
    for field in ("loadouts", "potentials", "album", "stats", "rebirths", "rebirth_levels",
                  "pick_order", "pick_limits", "pick_fill", "pick_bans", "endless_auto_pick"):
        need(before[field] == after[field], f"character preparation changed: {field}")
    # The game itself can activate a newly tamed pet when no pet was selected.
    if before["pet"]:
        need(before["pet"] == after["pet"], "character preparation changed: pet")
    need(any("AUTOPICK t=" in out.read_text(encoding="utf-8") for out in driven.outputs),
         "native auto-pick did not apply a level-up")


def stop(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    last = status.get("last") or {}
    need(last, "no last run")
    need(int(last.get("kills") or 0) > 0, "kills == 0")
    need(float(last.get("game_s") or 0) > 0, "game_s == 0")
    _marker(run, "STOP max_minutes")


def endless(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    last = status.get("last") or {}
    need(last.get("victory"), "last.victory false")
    need(last.get("endless"), "last.endless false")
    need(int(last.get("endless_mvps") or 0) >= 1, "endless_mvps == 0")
    need(int(last.get("kills") or 0) > 0, "kills == 0")
    _marker(run, "ENDLESS_DONE")


def run_stall(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    _marker(run, "RUN_STALL")
    _marker(run, "tries=3")
    need((status.get("last") or {}).get("forced"), "frozen run was not forced")


def failed(run: Run, driven: Driven, status: dict, reason: str) -> None:
    _exit(driven, 1)
    need(status.get("phase") == "failed", "phase != failed")
    need(status.get("terminal"), "terminal false")
    need(status.get("failed"), "failed false")
    need(status.get("finish_reason") == reason, f"finish_reason != {reason}")
    need(int(status.get("exit_code") or 0) != 0, "exit_code == 0")
    need(status.get("last_transition"), "last_transition empty")
    _marker(run, f"FAIL {reason}")


def flush_failed_keep(run: Run, driven: Driven, status: dict) -> None:
    failed(run, driven, status, "flush_failed")
    need("at keep" in status.get("last_error", ""), "failure does not identify the keep boundary")
    need(any(b"Save: cannot write" in path.read_bytes() for path in driven.outputs),
         "native save did not report a failed write")
    _marker(run, "SETTLE ")
    checkpoint = json.loads(run.artifact("checkpoint.json").read_bytes())
    totals = status["totals"]
    need(checkpoint.get("phase") == "run" and checkpoint.get("run_id") == status.get("run_id")
         and checkpoint.get("session") == run.session, "checkpoint advanced despite the failed save")
    need(totals == checkpoint.get("totals") and totals["started"] == 1 and totals["runs"] == 0
         and totals["zeny"] == 0 and totals["coins"] == 0 and totals["ymir"] == 0,
         "failed run was credited")
    need(not checkpoint.get("result") and not status.get("last") and not _journal(run.artifact("journal.jsonl")),
         "failed run was published")


def checkpoint_corrupt(run: Run, driven: Driven, status: dict) -> None:
    failed(run, driven, status, "checkpoint_corrupt")
    snapshot, = (run.work / "install-backups").glob("install-*/profile.json")
    need((run.profile / "profile.json").read_bytes() == snapshot.read_bytes(),
         "profile changed although the session could not start")


def _journal(path: Path) -> list[dict]:
    return read_jsonl(path) if path.is_file() else []


def run_choice(run: Run, driven: Driven, status: dict, expected: tuple[tuple[str, int], ...],
               oath_points: tuple[int, ...] = (), *, attempts: tuple[str, ...] = ("finished",)) -> None:
    _exit(driven)
    _done(status)
    target = status.get("target") or {}
    need((target.get("stage"), target.get("danger")) == expected[-1], "wrong location or difficulty in status target")
    rows = _journal(run.artifact("journal.jsonl"))
    need([r.get("run_id") for r in rows] == [f"{run.session}-r{i+1}" for i in range(len(expected))],
         "wrong run ids in journal")
    need(tuple((r.get("stage"), r.get("danger")) for r in rows) == expected, "wrong location or difficulty in journal")
    last = status.get("last") or {}
    need((last.get("stage"), last.get("danger")) == expected[-1], "wrong location or difficulty in status last run")
    if oath_points:
        need(tuple(r.get("oath_points") for r in rows) == oath_points, "wrong oath points in journal")
        need(target.get("oath_points") == status["last"].get("oath_points") == oath_points[-1],
             "wrong oath points in status")
        saved = status.get("oath_evidence") or {}
        need({"before", "after"} <= saved.keys(), "missing saved oath snapshots")
        need(saved["before"] == saved["after"], "saved oath set changed")
        if not any(oath_points):
            need(saved["before"], "this scenario requires a profile with saved oaths to test that they are not inherited")
    outcome = driven.outcome or {}
    need(tuple(a["outcome"] for a in outcome.get("attempts", [])) == attempts, "wrong session attempt outcomes")
    session_notes = [r for r in read_history(run.os) if r.get("session_id") == run.session]
    need(len(session_notes) == 1, "no completed session in history")
    need(session_notes[0].get("run_choices") == [
        {key: r[key] for key in ("run_id", "stage", "danger", "oath_points",
                                 "kept", "keep_skipped", "falls_by_mechanic")
         if key in r and (key not in ("kept", "keep_skipped") or r[key])} for r in rows
    ], "history did not retain the location, difficulty, oath points and fall counts of each run")


def _unlocked_locations(run: Run) -> list[dict]:
    data = read_catalog(run.os, run.profile)
    if data is None:
        raise VerificationFailure("no valid catalog")
    locations = [row for row in data["locations"] if row["unlocked"]]
    need(len(locations) >= 2, "this scenario requires at least two unlocked locations")
    return locations


def _rotation_start(run: Run, locations: list[dict]) -> int:
    logs = (run.artifact("crash.farmer.log"), run.artifact("farmer.log"))
    starts = [start for log in logs if log.is_file()
              for start in re.findall(r"^FARMER \S+ ROTATION_START stage=(\S+) selection=random$",
                                      log.read_text(encoding="utf-8"), re.MULTILINE)]
    need(len(starts) == 1, "rotation must log exactly one random start per session")
    ids = [row["id"] for row in locations]
    need(starts[0] in ids, "rotation started at a locked or unknown location")
    return ids.index(starts[0])


def location_rotation(run: Run, driven: Driven, status: dict, count: int) -> None:
    locations = _unlocked_locations(run)
    need(count > len(locations), "scenario did not cover a full rotation")
    start = _rotation_start(run, locations)
    expected = tuple((locations[(start + i) % len(locations)]["id"], 30) for i in range(count))
    run_choice(run, driven, status, expected, (6,) * count, attempts=("failed", "finished"))
    game = status.get("game") or {}
    need((game.get("stage"), game.get("danger")) == expected[-1], "the game ended at the wrong location or difficulty")


# Rebirth jobs by class and job path (game_data.gd CLASSES job2/job2_alt.trans).
_REBIRTH_JOBS = {
    "swordsman": ("lord_knight", "paladin"), "mage": ("high_wizard", "professor"), "archer": ("sniper", "clown"),
    "thief": ("assassin_cross", "stalker"), "acolyte": ("high_priest", "champion"), "merchant": ("whitesmith", "creator"),
}


def hell_rotation(run: Run, driven: Driven, status: dict, *, stage: str | None = None) -> None:
    config = json.loads(run.artifact("json").read_bytes())
    cid = config["class"]
    path = config.get("job_paths", {}).get(cid, 0)
    job = _REBIRTH_JOBS.get(cid, ())[path:path + 1]
    need(job, f"no rebirth job known for {cid} path {path}")
    _exit(driven)
    _done(status)
    totals = status["totals"]
    need(totals["started"] == totals["runs"] == 1, "expected one completed run")
    rows = _journal(run.artifact("journal.jsonl"))
    need(len(rows) == 1 and rows[0].get("run_id") == f"{run.session}-r1", "expected one run in the journal")
    if stage is None:
        locations = _unlocked_locations(run)
        stage = locations[_rotation_start(run, locations)]["id"]
    for result in (status.get("last") or {}, rows[0]):
        need((result.get("stage"), result.get("danger")) == (stage, 30), "wrong location or difficulty")
        need(result.get("oath_points") == 37, "wrong oath points")
        need(not result.get("forced") and not result.get("force_reason"),
             f"run was forced: {result.get('force_reason') or 'unknown reason'}")
        if result.get("died"):
            log = run.artifact("farmer.log").read_text(encoding="utf-8")
            cause = next((line for line in reversed(log.splitlines()) if "PLAYER_DIED " in line), "")
            detail = cause or f"t={result.get('game_s')} s; no death cause logged"
            raise VerificationFailure(f"run ended in defeat: {detail}")
        need(result.get("job") == job[0], f"wrong job: expected {job[0]}, got {result.get('job')}")
        need(result.get("endless") and result.get("finale_won"), "did not defeat the final boss in endless")
        need(result.get("victory") is True, "victory missing")
    need(totals.get("wins") == 1, "victory missing from totals")
    log = run.artifact("farmer.log").read_text(encoding="utf-8")
    need(re.search(r"KEEP_DONE .*victory=true free=true slots=3$", log, re.MULTILINE),
         "expected three free keep slots after victory")
    altars = re.findall(
        r"^FARMER \S+ ALTAR_TAKE id=(\w+) from=([\d.]+) nearby=\d+ t=[\d.]+ raid=(\w+) ref=(\d+)$",
        log, re.MULTILINE)
    need(any(float(distance) > 12 for _, distance, _, _ in altars), "no map-wide altar taken")
    priority = {"freyja", "loki", "niflheim", "thor", "yggdrasil", "valkyrie", "baldur", "odin", "emperium"}
    need(all(altar in priority for altar, _, _, _ in altars), "took an altar not allowed by Hell policy")
    need(all(raid == "portal" for altar, _, raid, _ in altars if altar == "baldur"),
         "Baldur taken outside portal window")
    skips = re.findall(r"ALTAR_SKIP id=(\w+) reason=(\w+) t=[\d.]+ raid=(\w+) ref=(\d+)$", log, re.MULTILINE)
    need(all(altar == "baldur" and raid == "idle" for altar, reason, raid, _ in skips
             if reason == "baldur_waits_portal"), "invalid Baldur field skip")
    interrupted = {ref for _, reason, _, ref in skips if reason == "channel_interrupted"}
    need(not any(ref in interrupted for _, _, _, ref in altars), "took an altar after its channel was interrupted")

    mvps = list(re.finditer(r"^FARMER \S+ BOSS_WON .* mvps=(\d+) ", log, re.MULTILINE))
    routes = list(re.finditer(r"^FARMER \S+ KARMA_ROUTE side=light mvp=reginleif after_mvp=(\d+) ", log, re.MULTILINE))
    kills = list(re.finditer(r"^FARMER \S+ VALKYRIE_KILLED mvp=reginleif after_mvp=(\d+) boons=(\d+) ",
                            log, re.MULTILINE))
    endless = list(re.finditer(r"^FARMER \S+ ENDLESS_START .* n=(\d+)$", log, re.MULTILINE))
    count = len(mvps)
    # Native run_mvps also counts the Morroc finale, which has no Valhalla route.
    need(count > 0 and all(row.get("run_mvps") == count * 2 + 1 for row in (status["last"], rows[0])),
         "MVP count does not match the run journal")
    need(len(endless) == count, "expected endless to continue once per regular MVP")
    for n, (mvp, continuation) in enumerate(zip(mvps, endless, strict=True), 1):
        mvp_id = str(2 * n - 1)
        need(mvp[1] == mvp_id and continuation[1] == str(n)
             and (n == 1 or endless[n - 2].end() < mvp.start()), "unexpected regular MVP sequence")
        need(n <= len(routes) and routes[n - 1][1] == mvp_id and mvp.end() < routes[n - 1].start(),
             f"no Valhalla route after MVP {mvp_id}")
        need(n <= len(kills) and kills[n - 1].groups() == (mvp_id, str(n))
             and routes[n - 1].end() < kills[n - 1].start() < continuation.start(),
             f"no Valkyrie kill before endless continued after MVP {mvp_id}")
    need(len(routes) == len(kills) == count and rows[0].get("valkyrie_kills") == count,
         "Valkyrie kill count does not match the run journal")


def valkyrie_drill(run: Run, driven: Driven, status: dict, *, count: int) -> None:
    _exit(driven)
    _done(status)
    need(status["totals"]["runs"] == count, "Valkyrie drill did not finish every fight")
    log = run.artifact("farmer.log").read_text(encoding="utf-8")
    rows = re.findall(
        r"^FARMER \S+ VALKYRIE_DRILL run=(\d+) ability=(\w+) danger=30 oaths=37 "
        r"marks=(\d+) contacts=(\d+) hits=(\d+) died=(true|false) cause=(.*)$", log, re.MULTILINE)
    expected = Counter("spear spears pillars starfall judgment aegis einherjar seals charge scales".split())
    expected["starfall"] += count - 10
    need([int(n) for n, *_ in rows] == list(range(1, count + 1))
         and Counter(row[1] for row in rows) == expected, "missing D30/37-oath Valkyrie fight evidence")
    waves = [(n, marks, contacts, hits, died, cause)
             for n, ab, marks, contacts, hits, died, cause in rows if ab == "starfall"]
    failures = [row for row in waves if int(row[2]) > 0 or int(row[3]) > 0 or row[4] == "true"]
    need(not failures, f"Caída de Valhalla hit or killed the hero: {failures}")
    need(len(waves) >= 10 and all(marks == "6" for _, marks, *_ in waves),
         "expected ten complete six-mark Caída de Valhalla waves")


def hel_route_drill(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    need(status["totals"]["started"] == status["totals"]["runs"] == 1, "expected one completed Hel run")
    log = run.artifact("farmer.log").read_text(encoding="utf-8")
    mvps = list(re.finditer(r"^FARMER \S+ BOSS_WON t=\S+ mvps=1 ", log, re.MULTILINE))
    routes = list(re.finditer(r"^FARMER \S+ KARMA_ROUTE side=dark mvp=randgris_fallen after_mvp=1 ", log, re.MULTILINE))
    kills = list(re.finditer(
        r"^FARMER \S+ RANDGRIS_KILLED mvp=randgris_fallen after_mvp=1 boons=(\d+) "
        r"t=\S+ revives=\d+ falls=\d+ boon=(\w+)$", log, re.MULTILINE,
    ))
    need(len(mvps) == len(routes) == 1 and mvps[0].end() < routes[0].start(),
         "Niflheim route was not entered after the regular MVP")
    need(len(kills) == 1 and routes[0].end() < kills[0].start(),
         "Fallen Randgris was not killed after entering Niflheim")
    need(kills[0].groups() == ("1", "hel_pact"), "Pact of Hel was not applied")
    rows = _journal(run.artifact("journal.jsonl"))
    need(len(rows) == 1 and rows[0].get("run_id") == f"{run.session}-r1", "expected one Hel run in the journal")
    row = rows[0]
    need(row.get("died") is False and row.get("falls_by_mechanic") == {}
         and not re.search(r"^FARMER \S+ PLAYER_(?:DIED|FELL) ", log, re.MULTILINE),
         "hero died or fell in the Hel route drill")
    need(row.get("victory") is True and not row.get("forced"), "Hel run did not settle normally as a win")
    need(row.get("karma_side") == "dark" and row.get("randgris_kills") == 1
         and any(timing.get("kind") == "randgris" and timing.get("boss") == "randgris_fallen"
                 and timing.get("kill_ms") is not None for timing in row.get("arena_timings", [])),
         "journal did not record the Fallen Randgris arena kill")


def mvp_mechanics(run: Run, driven: Driven, status: dict, *, trials: int) -> None:
    _exit(driven)
    _done(status)
    count = 3 * trials
    need(status["totals"]["runs"] == count, "MVP drill did not finish every trial")
    log = run.artifact("farmer.log").read_text(encoding="utf-8")
    rows = re.findall(
        r"^FARMER \S+ MVP_DRILL run=(\d+) ability=(spears|quake|slam) danger=30 oaths=37 "
        r"strikes=(\d+) contacts=(\d+) hits=(\d+) died=(true|false)$", log, re.MULTILINE,
    )
    expected = [ability for ability in ("spears", "quake", "slam") for _ in range(trials)]
    need([int(row[0]) for row in rows] == list(range(1, count + 1))
         and [row[1] for row in rows] == expected, "missing D30/37-oath MVP drill trials")
    failures = [row for row in rows if row[3:] != ("0", "0", "false")]
    need(not failures, f"MVP drill mechanic hit or killed the hero: {failures}")
    need(all(int(row[2]) == (2 if row[1] == "spears" else 1) for row in rows),
         "MVP drill did not witness every strike")
    journal = _journal(run.artifact("journal.jsonl"))
    need(len(journal) == count and all(row.get("falls_by_mechanic") == {} for row in journal),
         "MVP drill journal has missing or nonzero fall counts")


def blocked_portal(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    _marker(run, "BLOCKED_PORTAL seeded")
    _marker(run, "BLOCKED_PORTAL entered")


def field_navigation(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    for marker in ("FIELD_NAVIGATION seeded", "ALTAR_SKIP id=freyja reason=expires_first",
                   "ALTAR_TAKE id=loki from=16.0", "FIELD_NAVIGATION collected", "FIELD_NAVIGATION escaped"):
        _marker(run, marker)


def field_charge(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    log = run.artifact("farmer.log").read_text(encoding="utf-8")
    rows = re.findall(r" FIELD_CHARGE run=(\d+) contacts=(\d+) falls=(\d+) died=(true|false)$",
                      log, re.MULTILINE)
    need([row[0] for row in rows] == ["1", "2", "3", "4"], "missing native charge trials")
    need(all(row[1:] == ("0", "0", "false") for row in rows), f"field charge hit the hero: {rows}")


def location_rotation_resume(run: Run, driven: Driven, status: dict) -> None:
    locations = _unlocked_locations(run)
    start = _rotation_start(run, locations)
    selected = [locations[(start + i) % len(locations)] for i in range(3)]
    expected = tuple((row["id"], 30 if i < 2 else row["min_difficulty"]) for i, row in enumerate(selected))
    run_choice(run, driven, status, expected, attempts=("failed", "finished"))


def native_progress_parity(run: Run, driven: Driven, status: dict) -> None:
    run_choice(run, driven, status, expected=(("prontera", 30),), attempts=("failed", "finished"))
    row, = _journal(run.artifact("journal.jsonl"))
    need(row["victory"] and not row["forced"] and row["oath_points"] == 37, "expected a native D30/37 win")
    evidence = row["progress"]
    need(evidence["run_id"] == row["run_id"] and evidence["mvps"] > 0, "no native progress from the winning run")
    need(evidence["board_requests"] == 0 and evidence["net_mode"] == "", "network activity during settlement")
    before, after = evidence["before"], evidence["after"]
    history = after["history"]
    need(history and history[1:] == before["history"][:49], "native Album history was not appended exactly once")
    entry = history[0]
    need(entry["class"] == row["class"] and entry["stage"] == row["stage"] and entry["danger"] == 30
         and entry["victory"] is True and entry["mvps"] == evidence["mvps"]
         and abs(entry["time"] - row["game_s"]) <= 0.5, "native Album row did not describe this win")
    need(after["hell_maps"] == before["hell_maps"] | {row["stage"]: True}
         and after["hell_classes"] == before["hell_classes"] | {row["class"]: True}, "Hell title progress differs")
    need(after["oath_best"] == before["oath_best"] | {row["stage"]: 37}, "oath best did not advance to 37")
    need({"hell_15", "oath_max"} <= after["titles"].keys(), "missing native Hell/oath title records")
    takes = evidence["altar_takes"]
    need(takes > 0 and after["altars"] == before["altars"] + takes
         and after["altars_run"] == max(takes, before["altars_run"]), "native altar counters disagree with altar takes")
    need(before["cloud_rev"] == after["cloud_rev"] and before["world_feats"] == after["world_feats"],
         "settlement changed online profile or queued a world-chat feat")
    _marker(run, "TEST_CRASH settled", suffix="crash.farmer.log")
    need(status.get("progress_saved") == after, "recovery changed the native progression a second time")


def _tower_rank(snapshot: dict) -> tuple[int, float, float]:
    return snapshot["level"], snapshot["xp_progress"], snapshot["saved_at"]


def _tower_done(driven: Driven, status: dict) -> None:
    if status.get("phase") == "failed":
        raise VerificationFailure(f"{status.get('finish_reason')}: {status.get('last_error')}")
    _exit(driven)
    _done(status)


def tower_snapshot_parity(run: Run, driven: Driven, status: dict) -> None:
    _tower_done(driven, status)
    rows = _journal(run.artifact("journal.jsonl"))
    need(len(rows) == status["totals"]["runs"] == 2, "expected two settled D30 runs")
    need(all(row["stage"] == "prontera" and row["danger"] == 30 for row in rows), "wrong D30 run choice")
    evidence = status["tower_evidence"]
    manual = evidence["before"]
    need(len(manual) == 10 and sum(not snap["locked"] for snap in manual) == 9
         and not any(snap["farmer"] for snap in manual), "wrong manual Tower fixture")
    saved = []
    for i, row in enumerate(rows, 1):
        builds = evidence[str(i)]
        need([snap for snap in builds if not snap["farmer"]] == manual, "manual Tower snapshots changed")
        candidates = [snap for snap in builds if snap["farmer"]]
        need(len(candidates) == 1, "expected exactly one farmer Tower snapshot after each run")
        saved.append(candidates[0])
        need(row["player_level"] >= 20, "ordinary D30 hero did not reach the native eligibility threshold")
    need(saved[0]["level"] == rows[0]["player_level"], "the first run's snapshot has the wrong level")
    need(saved[1]["id"] != saved[0]["id"] and saved[1]["level"] == rows[1]["player_level"]
         and _tower_rank(saved[1]) > _tower_rank(saved[0]), "better run did not replace the farmer snapshot")
    catalog = json.loads(run.artifact("catalog.json").read_bytes())["tower"]
    need(catalog["open"] is True, "Tower catalog did not reflect unlock")
    need([snap["id"] for snap in catalog["snapshots"] if snap["farmer"]] == [saved[1]["id"]],
         "Tower catalog did not publish the replacement snapshot")


def tower_one_run(run: Run, driven: Driven, status: dict) -> None:
    _tower_done(driven, status)
    need(status["finish_reason"] == "tower_finished", "wrong Tower session outcome")
    totals = status["totals"]
    rows = _journal(run.artifact("journal.jsonl"))
    need(len(rows) == totals["started"] == totals["runs"] == 1 and totals["lost"] == totals["wins"] == 0,
         "expected exactly one settled Tower run and no win")
    row = rows[0]
    chosen_floor = json.loads(run.artifact("json").read_bytes())["stage"]["floor"]
    need(row["stage"] == "tower" and row["tower_floor_start"] == chosen_floor
         and row["tower_floor_best"] >= chosen_floor + 1, "wrong Tower journal floors")
    need(row["victory"] is row["finale_won"] is False and row["end_cause"] in {"death", "finish"}
         and row["died"] is (row["end_cause"] == "death"), "Tower death/Finish was treated as a win")
    if row["end_cause"] == "finish":
        need(row["force_reason"] == "finish" and not (run.profile / "farmer_command").exists(),
             "Tower did not consume the Finish command")
    evidence = status["tower_evidence"]
    before = evidence["before"]
    chosen = max((snap for snap in before if not snap["locked"]), key=_tower_rank, default=None)
    need(chosen and row["snapshot"] == {key: chosen[key] for key in ("id", "level", "job")},
         "wrong Tower snapshot selected")
    need(evidence["after"] == [snap for snap in before if snap["id"] != row["snapshot"]["id"]],
         "did not consume exactly the selected snapshot")
    prep_before, prep_after = evidence["preparation_before"], evidence["preparation_after"]
    need(prep_before and prep_after, "missing Tower preparation evidence")
    for field in prep_before.keys() | prep_after.keys():
        if field != "free_points" and (field != "pet" or prep_before["pet"]):
            need(prep_before.get(field) == prep_after.get(field), f"character preparation changed: {field}")
    need(evidence["autopilot_at_end"] is True and evidence["board_requests"] == 0,
         "online submission during Tower settlement")
    _marker(run, f"TOWER_START run={row['run_id']} kind=normal floor={chosen_floor}")
    _marker(run, f"TOWER_FLOOR cleared={row['tower_floor_best']}")
    checkpoint = json.loads(run.artifact("checkpoint.json").read_bytes())
    need(checkpoint["tower_intent"] == {"run_id": row["run_id"], "snapshot_id": row["snapshot"]["id"]},
         "Tower intent was not retained through settlement")


def tower_crash_recovery(run: Run, driven: Driven, status: dict) -> None:
    failed(run, driven, status, "tower_intent_unresolved")
    cases = json.loads(run.artifact("crash-cases.json").read_bytes())
    for point in TOWER_CRASH_POINTS:
        case = cases[point]
        checkpoint = case["checkpoint"]
        saved_status = case["restart_status"]
        need(case["first_exit"] != 0 and case["crash_marker"] == point, f"did not crash at {point}")
        _marker(run, f"TEST_CRASH {point}", suffix=f"{point}.crash.farmer.log")
        need(case["restart_exit"] == 1 and saved_status["phase"] == "failed"
             and saved_status["terminal"] and saved_status["failed"]
             and saved_status["finish_reason"] == "tower_intent_unresolved",
             f"{point}: restart did not fail closed")
        intent = checkpoint["tower_intent"]
        session = f"{run.session}-{point}"
        need(checkpoint["session"] == saved_status["session"] == session
             and checkpoint["run_id"] == intent["run_id"] == f"{session}-r1"
             and checkpoint["phase"] == "tower_intent" and intent["snapshot_id"],
             f"{point}: missing durable launch intent")
        evidence = case["evidence"] or {}
        before, at_crash = evidence.get("before_crash"), evidence.get("at_crash")
        if not before or not at_crash or not before["snapshots"]:
            raise VerificationFailure(f"{point}: missing native save evidence")
        chosen = max((snap for snap in before["snapshots"] if not snap["locked"]), key=_tower_rank, default=None)
        if not chosen or chosen["id"] != intent["snapshot_id"]:
            raise VerificationFailure(f"{point}: intent names the wrong snapshot")
        expected = before["snapshots"] if point == "tower_intent" else [
            snap for snap in before["snapshots"] if snap["id"] != chosen["id"]
        ]
        need(at_crash["snapshots"] == expected, f"{point}: unexpected Tower snapshot spend")
        need(before["preparation"] == at_crash["preparation"], f"{point}: character preparation changed")
        need(before["other_sha256"] == at_crash["other_sha256"], f"{point}: non-Tower profile data changed")
        need(evidence["board_requests"] == 0, f"{point}: online submission during Tower launch")
        need(case["before_restart"] == case["after_restart"], f"{point}: restart changed the saved profile")
        need(checkpoint == case["checkpoint_after_restart"] and saved_status["totals"]["runs"] == 0,
             f"{point}: restart advanced the unprovable run")
    need(not _journal(run.artifact("journal.jsonl")), "an unprovable Tower run was journaled")


def invalid_rotation_difficulty(run: Run, driven: Driven, status: dict) -> None:
    locations = _unlocked_locations(run)
    need(locations[0]["min_difficulty"] == 1, "difficulty 1 is not valid for the first location")
    incompatible = next((row["id"] for row in locations[1:] if row["min_difficulty"] > 1), None)
    if incompatible is None:
        raise VerificationFailure("this scenario requires an unlocked location with minimum difficulty above 1")
    invalid_choice(run, driven, status, field="difficulty", selection=f"location '{incompatible}'")


def wishlist_keep(run: Run, driven: Driven, status: dict, *, keep_unowned: bool = False) -> None:
    rows = _journal(run.artifact("journal.jsonl"))
    count = 3 if keep_unowned else 2
    run_choice(run, driven, status, expected=(("prontera", 1),) * count)
    evidence = status.get("wishlist_evidence", [])
    need(len(evidence) == count, f"missing {count} keep snapshots")
    ids = evidence[0]["fixture_ids"]
    need(len(ids) == len(set(ids)) == 3 and all(ids == data["fixture_ids"] for data in evidence),
         "missing fixture items")
    expensive, wanted, other = ids
    expected_keeps = [[wanted], [other] if keep_unowned else []] + ([[]] if keep_unowned else [])
    for index, (data, row) in enumerate(zip(evidence, rows, strict=True)):
        need(data["wishlist"] == [expensive, wanted] and not data["free"], "not a paid wishlist offer")
        before, after = data["before"], data["after"]
        offer = data["offer"]
        drops = {item["id"]: item for item in offer}
        need(all(item in drops and drops[item]["legend_coins"] > 0 for item in ids),
             "fixture legendaries are missing from the game's offer")
        if keep_unowned:
            need(offer[0]["id"] == other, "non-wishlist fixture must be offered before the wishlist")
        expected = expected_keeps[index]
        added = Counter(after["stored_ids"]) - Counter(before["stored_ids"])
        need(added == Counter(expected), "wrong items added to saved storage")
        owned_other = int(keep_unowned and index >= 1)
        need(after["stored_ids"].count(wanted) == 1 and after["stored_ids"].count(other) == owned_other,
             "incorrect ownership after keep")
        need(row["kept"] == expected, "journal kept items disagree with saved storage")
        skips = {item["id"]: item["reason"] for item in row["keep_skipped"]}
        need(skips.get(expensive) == "over_zeny_limit", "journal did not record the unaffordable item")
        if index:
            need(before["stored_ids"].count(wanted) == 1 and skips.get(wanted) == "already_owned",
                 "owned wishlist item did not persist or was not skipped")
        if keep_unowned and index != 1:
            reason = "already_owned" if index else "no_keep_slots"
            need(skips.get(other) == reason, f"non-wishlist item was not skipped for {reason}")
        spent = sum(drops[item]["cost"] for item in expected)
        need(after["zeny"] == before["zeny"] + sum(i["sell_zeny"] for i in offer) - spent
             and (not expected or spent > 0), "wrong zeny debited for paid keep")
        expected_cash = sum(i["legend_coins"] for i in offer) - sum(drops[item]["legend_coins"] for item in expected)
        need(after["legend_coins"] == before["legend_coins"] + expected_cash, "legendary offers were not cashed in")
    log = run.artifact("farmer.log").read_text(encoding="utf-8")
    need(any(wanted in line and "already_owned" in line for line in log.splitlines()),
         "owned wishlist skip and reason missing from log")


def invalid_choice(run: Run, driven: Driven, status: dict, field: str, selection: str) -> None:
    _exit(driven, 2)
    reason = "invalid_" + field
    need(status.get("phase") == "failed" and status.get("terminal") and status.get("failed"), "no terminal failure")
    need(status.get("finish_reason") == reason, f"finish_reason != {reason}")
    need(status.get("exit_code") and (status.get("totals") or {}).get("started") == 0,
         "invalid choice was allowed to start a run")
    need(not _journal(run.artifact("journal.jsonl")), "invalid choice created a journal entry")
    outcome = driven.outcome or {}
    need(outcome.get("kind") == "quarantined" and outcome.get("reason") == reason, "choice was not quarantined")
    attempts = outcome.get("attempts", [])
    need(len(attempts) == 1 and attempts[0]["outcome"] == "fatal", "supervisor retried an invalid choice")
    detail = attempts[0].get("detail", "")
    need(field in detail.lower() and selection in detail, "failure detail did not name the invalid field and value")


def command(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    name = run.name
    _done(status, needs_run=name != "cmd-abort")
    _marker(run, "FINISH")
    log = run.artifact("farmer.log").read_text(encoding="utf-8")
    checkpoint = json.loads(run.artifact("checkpoint.json").read_bytes())
    session, totals = status["session"], status["totals"]
    rows = [row for row in _journal(run.artifact("journal.jsonl")) if row["session"] == session]
    abort, paused = name.startswith("cmd-abort"), name == "cmd-pause-resume"
    started = 2 if paused else 1
    lost = int(name == "cmd-abort")
    runs = started - lost
    reason = "abort" if abort else "max_runs" if paused else "finish"
    need(status.get("finish_reason") == reason, f"finish_reason != {reason}")
    need(status.get("exit_code") == 0, "exit_code != 0")
    need(checkpoint.get("phase") == "idle" and checkpoint.get("session") == session,
         "checkpoint is not idle in the same session")
    need(checkpoint.get("totals") == totals, "checkpoint totals differ from status")
    need((totals.get("started"), totals.get("runs"), totals.get("lost")) == (started, runs, lost),
         f"expected {started} started, {runs} settled and {lost} lost")
    need([r["run_id"] for r in rows] == [f"{session}-r{i}" for i in range(1, runs + 1)], "wrong journal run IDs")
    need(totals.get("zeny") == sum(r["zeny_gain"] for r in rows), "totals.zeny != journal zeny_gain sum")
    need(not any((run.profile / f).exists() for f in ("farmer_command", "farmer_command.claimed", "farmer_stop")),
         "unconsumed farmer command")
    need(log.count(" SETTLE ") == runs, f"expected {runs} SETTLE markers")
    if abort:
        need(" KEEP_DONE " not in log and " MAINT " not in log, "abort performed keep or maintenance")
        need(all(not r["kept"] for r in rows), "abort kept an item")
    else:
        need(log.count(" KEEP_DONE ") == log.count(" MAINT ") == started,
             f"expected {started} KEEP_DONE and MAINT markers")
        force = "run_timeout" if paused else "finish"
        need(all(r["force_reason"] == force for r in rows), f"journal force_reason != {force}")


def recovered(run: Run, driven: Driven, status: dict, point: str, marker: str, *, supervised: bool = False) -> None:
    _exit(driven)
    boot_path = run.artifact("crash.farmer.log")
    need(boot_path.is_file(), "no attempt-1 farmer.log")
    boot_log = boot_path.read_text(encoding="utf-8")
    if supervised:
        outcome = driven.outcome or {}
        attempts = outcome.get("attempts") or []
        number_and_outcome = [(a.get("number"), a.get("outcome")) for a in attempts]
        need(number_and_outcome == [(1, "failed"), (2, "finished")],
             "supervisor did not fail attempt 1 and finish attempt 2")
    else:
        need(driven.crash_code not in (None, 0, 124), f"crash launch exit {driven.crash_code} (expected killed farmer)")
    if supervised and point == "run":
        need(driven.killed_r1, "the game was not killed in run r1")
    else:
        need(f"TEST_CRASH {point}" in boot_log, f"crash launch did not reach {point}")
    need(status.get("phase") == "done" and not status.get("failed"), "phase != done")
    need(status.get("session") == run.session, "session id not continued")
    totals = status.get("totals") or {}
    journal = run.artifact("journal.jsonl")
    need(journal.is_file(), "no farmer_runs.jsonl")
    rows = [row for row in _journal(journal) if row.get("session") == run.session]
    ids = Counter(row.get("run_id") for row in rows)
    need(all(count == 1 for count in ids.values()), f"duplicate journal run_id: {dict(ids)}")
    need(int(totals.get("runs") or 0) == len(rows), f"totals.runs {totals.get('runs')} != journal {len(rows)}")
    zeny = int(totals.get("zeny") or 0)
    need(zeny == sum(int(row.get("zeny_gain") or 0) for row in rows), "totals.zeny != journal zeny_gain sum")
    need(int(totals.get("started") or 0) == 2, f"totals.started {totals.get('started')} != 2")
    boot = re.search(r" BOOT .* zeny=(\d+)", boot_log)
    if boot is None:
        raise VerificationFailure("no BOOT zeny in the crash launch log")
    moved = int((status.get("profile") or {}).get("zeny") or 0) - int(boot.group(1))
    need(moved == zeny, f"profile zeny moved {moved} != totals.zeny {zeny}")
    lost = int(point == "run")
    need(int(totals.get("lost") or 0) == lost, f"totals.lost {totals.get('lost')} != {lost}")
    need(set(ids) == {f"{run.session}-r{i}" for i in range(lost + 1, 3)}, f"wrong journal IDs: {list(ids)}")
    _marker(run, marker)


def soak(run: Run, driven: Driven, _status: dict) -> None:
    ok, problems, summary = judge_files(run.artifact("samples.jsonl"), run.artifact("journal.jsonl"),
                                        run.artifact("status.json"), session=run.session,
                                        supervisor_exit=driven.code, min_hours=run.soak_hours)
    lines = [json.dumps(summary), *(f"soak: FAIL {failure}" for failure in problems),
             "soak: PASS" if ok else "soak: FAIL"]
    path = run.artifact("verdict.log")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    need(ok, f"soak check failed (see {path.name})")
