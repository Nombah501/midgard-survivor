"""Scenario registry and artifact collection for one isolated verification worker."""

import json
import math
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from ..assets import presets_dir
from ..core import catalog, farmer_patch, patch_info, smoke
from ..core.commands import LocationRotation, SessionSettings
from ..core.supervisor import Policy
from ..platform import Platform
from . import drive, judges, soak


@dataclass(frozen=True)
class Scenario:
    timeout: float
    cfg: dict[str, object]
    driver: Callable[[drive.Run, float], drive.Driven]
    judge: Callable[[drive.Run, drive.Driven, dict], None]
    linux_only: bool = False
    preset: str | None = None


_SHORT: dict[str, object] = {"run_minutes": 0.2, "stall_seconds": 10.0}
_COMMANDS = _SHORT | {"max_runs": 2}
_OATH_RUNS = _SHORT | {"max_runs": 2, "danger_ceiling": 30}
_OATH_TARGETS = (("prontera", 30), ("prontera", 30))
_resume_settings = partial(SessionSettings, upgrades=False, card_fusion=False)
_ROTATION: LocationRotation = {"mode": "rotation"}
_ROTATION_RUNS = 24  # Patch 0.2.5 has 23 catalog locations; include wraparound.
_HELL_OATHS = {"tough": 3, "hunt": 3, "kyrie": 3, "elite": 3, "mvp_fury": 2,
               "hellfire": 3, "lex": 2, "curse": 2, "unlucky": 2}
_VALKYRIE_RUNS = 19  # One of each ability, plus nine more Caída waves.
_MVP_DRILL_TRIALS = 5
_HELL_RUN: dict[str, object] = {
    "class": "thief", "job_paths": {"thief": 0}, "danger": 30, "max_runs": 1, "oaths": _HELL_OATHS,
}
# Bounded scenarios inherit the shared one-run config, including speed 10,
# hard exit and display false. All check exits, evidence and script errors.
SCENARIOS = {
    # Done + terminal metadata, a win and last victory, kills/zeny > 0, FINISH.
    "one-run": Scenario(300, {}, drive.direct, judges.one_run),
    "watch-mode": Scenario(300, {"display": True}, drive.supervised, judges.watch_mode),
    "catalog": Scenario(300, {}, partial(drive.direct, FARMER_TEST_CATALOG="1"), judges.catalog),
    "preparation-unchanged": Scenario(300, {
        "auto_achievements": True, "auto_upgrades": True, "auto_sage": True, "auto_fuse": True,
        "auto_potential": True, "potential_reserve": 0, "potential_max_rolls": 500,
        "auto_storage_prune": True, "keep_reserve_slots": 500, "upgrade_reserve": 0,
    }, partial(drive.direct, FARMER_TEST_PREPARATION="1"), judges.preparation_unchanged),
    "wishlist-keep": Scenario(120, _SHORT | {"max_runs": 2, "keep_max_pct": 0.20, "auto_achievements": False},
                              partial(drive.supervised, FARMER_TEST_WISHLIST="1"), judges.wishlist_keep),
    "keep-unowned-legendaries": Scenario(120, _SHORT | {
        "max_runs": 3, "keep_max_pct": 0.20, "auto_achievements": False, "keep_unowned_legendaries": True,
    }, partial(drive.supervised, FARMER_TEST_WISHLIST="1"), partial(judges.wishlist_keep, keep_unowned=True)),
    "run-choice": Scenario(120, _SHORT | {"objective": "progress", "danger_ceiling": 1, "danger": 2},
                           drive.supervised, partial(judges.run_choice, expected=(("prontera", 2),))),
    "run-choice-resume": Scenario(180, _SHORT | {"max_runs": 2},
                                  partial(drive.supervised, resume=_resume_settings("prontera", 2)),
                                  partial(judges.run_choice, expected=(("prontera", 1), ("prontera", 2)))),
    "location-rotation": Scenario(300, _OATH_RUNS | {
        "stage": _ROTATION, "danger": 30, "oaths": {"tough": 3, "elite": 1}, "max_runs": _ROTATION_RUNS,
    }, partial(drive.supervised, crash_at="settled", FARMER_TEST_OATHS="1"),
       partial(judges.location_rotation, count=_ROTATION_RUNS)),
    "location-rotation-resume": Scenario(180, _SHORT | {
        "stage": _ROTATION, "danger": 30, "max_runs": 3, "danger_ceiling": 1, "objective": "progress",
    }, partial(drive.supervised, crash_at="settled", resume=_resume_settings(_ROTATION), resume_after_runs=1),
       judges.location_rotation_resume),
    "native-progress-parity": Scenario(360, _HELL_RUN | {
        "stage": "prontera", "endless": False, "run_minutes": 12.0, "karma_route": "natural",
        "auto_achievements": False,
    }, partial(drive.supervised, crash_at="settled", FARMER_TEST_PROGRESS="1"),
       judges.native_progress_parity, preset="hell-rotation.json"),
    "oaths": Scenario(180, _OATH_RUNS | {"danger": 30, "oaths": {"tough": 3, "elite": 1}},
                      partial(drive.supervised, FARMER_TEST_OATHS="1",
                              resume=_resume_settings("prontera", 30, {"hunt": 2})),
                      partial(judges.run_choice, expected=_OATH_TARGETS, oath_points=(6, 2))),
    "oaths-disabled": Scenario(180, _OATH_RUNS | {"danger": "auto", "objective": "progress"},
                               partial(drive.supervised, FARMER_TEST_OATHS="1",
                                       resume=_resume_settings("prontera", 30)),
                               partial(judges.run_choice, expected=_OATH_TARGETS, oath_points=(0, 0))),
    "invalid-oath": Scenario(120, {"danger": 30, "oaths": {"not-an-oath": 1}}, drive.supervised,
                             partial(judges.invalid_choice, field="oath", selection="not-an-oath")),
    "invalid-oath-rank": Scenario(120, {"danger": 30, "oaths": {"mvp_fury": 3}}, drive.supervised,
                                  partial(judges.invalid_choice, field="oath", selection="mvp_fury")),
    "invalid-oath-difficulty": Scenario(120, {"danger": "auto", "oaths": {"tough": 1}}, drive.supervised,
                                        partial(judges.invalid_choice, field="oath", selection="fixed difficulty 30")),
    "invalid-location": Scenario(120, {"stage": "not-a-location"}, drive.supervised,
                                 partial(judges.invalid_choice, field="location", selection="not-a-location")),
    "invalid-difficulty": Scenario(120, {"danger": 31}, drive.supervised,
                                   partial(judges.invalid_choice, field="difficulty", selection="31")),
    "invalid-rotation-difficulty": Scenario(120, {"stage": _ROTATION}, drive.supervised,
                                            judges.invalid_rotation_difficulty),
    # Done + terminal metadata, last run with kills and game time, STOP max_minutes.
    "stop": Scenario(180, {"class": "thief", "max_minutes": 1.0, "stall_seconds": 10.0, "max_runs": 0},
                     drive.direct, judges.stop),
    # Done + terminal metadata, endless victory with an MVP and kills, ENDLESS_DONE.
    "endless": Scenario(360, {"endless": True, "endless_minutes": 1.0, "endless_mvps": 2}, drive.direct, judges.endless),
    "hell-rotation": Scenario(1800, _HELL_RUN | {"stage": _ROTATION},
                              drive.direct, judges.hell_rotation, preset="hell-rotation.json"),
    **{
        f"hell-rotation-{stage}": Scenario(
            1800, _HELL_RUN | {"stage": stage}, drive.direct,
            partial(judges.hell_rotation, stage=stage), preset="hell-rotation.json",
        )
        for stage in ("payon", "orc_dun", "nameless", "turtle")
    },
    "valkyrie-drill": Scenario(180, {
        "class": "thief", "stage": "prontera", "danger": 30, "oaths": _HELL_OATHS,
        "max_runs": _VALKYRIE_RUNS, "restart_seconds": 0, "endless": False,
    }, partial(drive.direct, FARMER_TEST_VALKYRIE="1"),
       partial(judges.valkyrie_drill, count=_VALKYRIE_RUNS), preset="hell-rotation.json"),
    "mvp-mechanics-drill": Scenario(240, _HELL_RUN | {
        "stage": "prontera", "max_runs": 3 * _MVP_DRILL_TRIALS, "restart_seconds": 0, "endless": False,
    }, partial(drive.direct, FARMER_TEST_MVP_MECHANICS="1"),
       partial(judges.mvp_mechanics, trials=_MVP_DRILL_TRIALS), preset="hell-rotation.json"),
    "blocked-portal": Scenario(45, {"class": "thief", "danger": 30, "run_minutes": 0.1},
                               partial(drive.direct, FARMER_TEST_BLOCKED_PORTAL="1"), judges.blocked_portal),
    "field-navigation": Scenario(45, {
        "class": "thief", "stage": "prontera", "danger": 1, "altar_policy": "map-wide", "run_minutes": 1.5,
    }, partial(drive.direct, FARMER_TEST_FIELD_NAVIGATION="1"), judges.field_navigation),
    "field-charge-drill": Scenario(90, {
        "class": "thief", "job_paths": {"thief": 0}, "stage": "prontera", "danger": 30,
        "oaths": _HELL_OATHS, "max_runs": 4, "restart_seconds": 0, "endless": False,
    }, partial(drive.direct, FARMER_TEST_FIELD_CHARGE="1"), judges.field_charge, preset="hell-rotation.json"),
    # Fail the native save during keep; do not advance the checkpoint or journal rewards.
    "flush-fail": Scenario(180, _SHORT, partial(drive.direct, FARMER_TEST_FLUSH_FAIL="keep"), judges.flush_failed_keep),
    # Hook crash, same session, 2 started / 1 lost, only r2 journaled, totals and saved zeny agree, RUN_LOST.
    "crash-run": Scenario(180, _SHORT, partial(drive.crash, point="run"),
                          partial(judges.recovered, point="run", marker="RUN_LOST")),
    # Hook crash after flush, same session, both runs journaled once, no lost run, zeny agrees, journal=appended.
    "crash-settled": Scenario(180, _SHORT | {"max_runs": 2}, partial(drive.crash, point="settled"),
                              partial(judges.recovered, point="settled", marker="journal=appended")),
    # Hook crash after journal, same totals/save/unique r1,r2 as settled, journal=present (no second append).
    "crash-journaled": Scenario(180, _SHORT | {"max_runs": 2}, partial(drive.crash, point="journaled"),
                                partial(judges.recovered, point="journaled", marker="journal=present")),
    # All command scenarios: DONE/FINISH, correct reason and zero status code,
    # idle checkpoint with matching totals, correct ordered journal IDs and zeny,
    # all command files consumed, exact settlement/keep/maintenance counts.
    # Finish during run: settle, keep and maintain r1; force_reason=finish.
    "cmd-finish": Scenario(75, _COMMANDS, partial(drive.direct, command=True), judges.command),
    # Abort during run: lose r1, no journal or settlement, no keep or maintenance.
    "cmd-abort": Scenario(75, _COMMANDS, partial(drive.direct, command=True), judges.command),
    # Abort at keep for r1: settled once, no items kept and no maintenance.
    "cmd-abort-settled": Scenario(75, _COMMANDS, partial(drive.direct, command=True, FARMER_TEST_WAIT_AT_KEEP="1"),
                                  judges.command),
    # Pause settles r1, heartbeat advances without new starts; resume r2 in the
    # same process, two complete runs (run_timeout), finish at max_runs.
    "cmd-pause-resume": Scenario(75, _COMMANDS, partial(drive.direct, command=True), judges.command),
    # farmer_stop alias during run has exactly the same finish/settlement semantics.
    "cmd-legacy": Scenario(75, _COMMANDS, partial(drive.direct, command=True), judges.command),
    # Exit 1 + failed terminal status with checkpoint_corrupt, FAIL marker, byte-identical profile.
    "checkpoint-corrupt": Scenario(120, _SHORT, drive.corrupt_checkpoint, judges.checkpoint_corrupt),
    # External kill in r1; supervisor must fail attempt 1 and finish attempt 2.
    # Same lost-r1/unique r2 and zeny checks as crash-run, plus RUN_LOST.
    "supervised-kill-run": Scenario(300, _SHORT, partial(drive.supervised, kill_run=True),
                                    partial(judges.recovered, point="run", marker="RUN_LOST", supervised=True), True),
    # Hook at settled in attempt 1; supervisor fails it and finishes attempt 2.
    # Same exactly-once accounting and zeny checks as crash-settled, plus journal=appended.
    "supervised-crash-settled": Scenario(300, _SHORT | {"max_runs": 2}, partial(drive.supervised, crash_at="settled"),
                                          partial(judges.recovered, point="settled", marker="journal=appended", supervised=True)),
    # Supervisor exit and final status; duration, heartbeat, RSS and disk thresholds;
    # at least one settlement, unique IDs and all journal-backed totals match.
    "soak": Scenario(1800, {}, partial(drive.supervised, sample=True), judges.soak, True),
    # Watchdog sees the run's own time frozen while the engine clock ticks
    # (2026-11-19 night: t=640 for 6.5 h): three RUN_STALL tries force the run
    # to end, and the session still finishes at max_runs.
    "run-stall": Scenario(180, {"run_minutes": 0.0, "stall_seconds": 5.0},
                          partial(drive.direct, FARMER_TEST_FREEZE_RUN_TIME="1"), judges.run_stall),
}


BOUNDED_SCENARIOS = tuple(name for name in SCENARIOS if name not in {"soak", "watch-mode"})


def check_supported(os_: Platform, name: str) -> None:
    if SCENARIOS[name].linux_only and os_.release_os != "linux":
        raise ValueError(f"{name} is Linux only (unsupported on this OS)")


def _stage_candidate(os_: Platform, candidate: Path) -> patch_info.PatchInfo:
    metadata = candidate / patch_info.info_path(os_).name
    info = patch_info.load(metadata)
    if info.farmer_hash != farmer_patch.farmer_hash():
        raise ValueError("candidate does not match the current farmer sources; build a fresh farmer patch first")
    patch_info.save(os_, patch_info.info_path(os_), info)
    os_.link_sandbox_pack(candidate / patch_info.INSTALLED_PACK, patch_info.built_pack_path(os_))
    return info


def _collect(run: drive.Run) -> None:
    for name, suffix in (("farmer.log", "farmer.log"), ("farmer_status.json", "status.json"),
                         ("farmer_runs.jsonl", "journal.jsonl"), ("farmer_session.json", "checkpoint.json"),
                         (catalog.FILENAME, "catalog.json")):
        path = run.profile / name
        if path.is_file():
            shutil.copyfile(path, run.artifact(suffix))


def run_scenario(os_: Platform, source: Path, candidate: Path, work: Path, out: Path, name: str, *,
                 hours: float = 0.0, soak_preset: Path | None = None, policy: Policy = Policy(),
                 stop_requested_at: Callable[[], float | None] = lambda: None) -> dict:
    """Run against a fresh worker home already redirected through the platform seam."""
    check_supported(os_, name)
    scenario = SCENARIOS[name]
    if name == "soak":
        if not math.isfinite(hours * 3600) or hours <= 0:
            raise ValueError("--soak needs a positive, finite number of hours")
        preset = json.loads((soak_preset or presets_dir() / "night.json").read_bytes())
        if not isinstance(preset, dict):
            raise ValueError("soak preset must be a JSON object")
        config = preset | {"max_minutes": hours * 60, "max_runs": 0, "hard_exit": True}
        timeout = int(hours * 3600) + scenario.timeout
    else:
        strategy = json.loads((presets_dir() / scenario.preset).read_bytes()) if scenario.preset else {}
        config = smoke.one_run_config() | strategy | scenario.cfg
        timeout = scenario.timeout

    work, out, source = work.resolve(strict=True), out.resolve(strict=True), source.absolute()
    source_root, candidate_root = source.resolve(strict=True), candidate.resolve(strict=True)
    godot_root = os_.godot_user_data_root().resolve()
    if (not work.is_relative_to(out) or not os_.app_data_dir().resolve().is_relative_to(work)
            or not godot_root.is_relative_to(work) or godot_root != os_.godot_sandbox(work)[0].resolve()
            or out.is_relative_to(source_root) or out.is_relative_to(candidate_root) or any(work.iterdir())):
        raise ValueError("verification requires empty, isolated Godot and app data directories")
    if os_.game_running():
        raise ValueError("the game is running; close it first (verification never touches the real profile)")
    if stop_requested_at() is not None:
        raise InterruptedError("verification interrupted before sandbox preparation")

    info = _stage_candidate(os_, candidate_root)
    profile, _ = smoke.prepare_sandbox(os_, source, work)
    run = drive.Run(os_, profile, work, out, name, f"verify-{uuid.uuid4().hex}", stop_requested_at, policy, hours)
    run.artifact("json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    driven = scenario.driver(run, timeout)
    _collect(run)
    status = run.status()
    reason = driven.failure
    if not reason:
        try:
            if name != "soak":
                judges.need(status, "no readable farmer_status.json")
            scenario.judge(run, driven, status)
            if name not in {"one-run", "soak"}:
                judges.need(not any(smoke.has_script_error(path) for path in driven.outputs), "script error in game output")
        except (judges.VerificationFailure, OSError, KeyError, ValueError, TypeError) as exc:
            reason = str(exc)

    if os_.game_running():
        reason = f"{reason}; game still running" if reason else "game still running"
    totals = status.get("totals") or {}
    last = status.get("last") or {}
    row = {
        "scenario": name, "verdict": "FAIL" if reason else "PASS", "exit": driven.code, "reason": reason,
        **{k: status.get(k) for k in ("phase", "terminal", "failed", "finish_reason", "exit_code", "run_id",
                                      "heartbeat_seq", "build", "target")},
        **{k: totals.get(k) if isinstance(totals, dict) else None for k in ("runs", "wins", "losses", "kills", "zeny")},
        "last": {k: last.get(k) if isinstance(last, dict) else None
                 for k in ("stage", "danger", "victory", "endless", "endless_mvps", "kills", "zeny_gain", "xp_gain",
                           "cards_gain", "kept", "keep_skipped", "game_s", "wall_s", "oath_points")},
        "build_sha256": info.result_sha256,
    }
    run.artifact("result.json").write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return row
