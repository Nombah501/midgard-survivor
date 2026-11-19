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
from ..core import farmer_patch, patch_info, smoke
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


_SHORT: dict[str, object] = {"run_minutes": 0.2, "stall_seconds": 10.0}
_COMMANDS = _SHORT | {"max_runs": 2, "auto_keep": True, "keep_on_defeat": True}
# Bounded scenarios inherit the shared one-run preset, including speed 10,
# hard exit and display false. All check exits, evidence and script errors.
SCENARIOS = {
    # Done + terminal metadata, a win and last victory, kills/zeny > 0, FINISH.
    "one-run": Scenario(300, {}, drive.direct, judges.one_run),
    # Done + terminal metadata, last run with kills and game time, STOP max_minutes.
    "stop": Scenario(180, {"class": "thief", "max_minutes": 1.0, "stall_seconds": 10.0, "max_runs": 0},
                     drive.direct, judges.stop),
    # Done + terminal metadata, endless victory with an MVP and kills, ENDLESS_DONE.
    "endless": Scenario(360, {"endless": True, "endless_minutes": 1.0, "endless_mvps": 2}, drive.direct, judges.endless),
    # Exit 1 + failed terminal status, flush_failed + nonzero status code, FAIL flush_failed.
    "flush-fail": Scenario(180, _SHORT | {"max_minutes": 0.5}, partial(drive.direct, FARMER_TEST_FLUSH_FAIL="1"),
                           partial(judges.failed, reason="flush_failed")),
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


BOUNDED_SCENARIOS = tuple(name for name in SCENARIOS if name != "soak")


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
                         ("farmer_runs.jsonl", "journal.jsonl"), ("farmer_session.json", "checkpoint.json")):
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
        config = preset | {"max_minutes": hours * 60, "max_runs": 0, "hard_exit": True, "display": False}
        timeout = int(hours * 3600) + scenario.timeout
    else:
        config = smoke.one_run_config() | scenario.cfg
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
                                      "heartbeat_seq", "build")},
        **{k: totals.get(k) if isinstance(totals, dict) else None for k in ("runs", "wins", "losses", "kills", "zeny")},
        "last": {k: last.get(k) if isinstance(last, dict) else None
                 for k in ("victory", "endless", "endless_mvps", "kills", "zeny_gain", "xp_gain", "cards_gain", "kept",
                           "game_s", "wall_s")},
        "build_sha256": info.result_sha256,
    }
    run.artifact("result.json").write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return row
