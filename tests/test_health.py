"""`python -m midgard_farm.health`: is the farm actually making progress?

2026-11-19 night: the heartbeat stayed fresh and the phase said `run` for 6.5 h
while the run's own time sat at t=640. Only comparing two samples tells
farming from stalled.
"""

import json
import os
import subprocess
import sys
import time

from midgard_farm import platform
from midgard_farm.core.state import ServiceState, StateKind
from midgard_farm.health import Verdict, judge

from test_profile import godot_root, make_profile

NOW = 1_800_000_000.0
MONOTONIC = 10_000.0


def status(phase="run", t=640.0, kills=13_557, zeny=27_000_000, runs=4, heartbeat=NOW,
           *, raid=False, run_id="run-1"):
    return {"phase": phase, "heartbeat": heartbeat, "session": "afk-1", "run_id": run_id, "pid": 42,
            "game": {"time": t, "kills": kills, "in_raid": raid}, "totals": {"zeny": zeny, "runs": runs}}


def test_advancing_run_time_is_progressing():
    verdict = judge(status(), status(t=655.0, kills=13_700, heartbeat=NOW + 15), seconds=15, now=NOW + 15)
    assert verdict.kind == Verdict.PROGRESSING
    assert verdict.exit_code == 0
    assert "+143 kills" in verdict.message


def test_fresh_heartbeat_with_frozen_run_time_is_stalled():
    verdict = judge(status(), status(heartbeat=NOW + 180), seconds=180, now=NOW + 180)
    assert verdict.kind == Verdict.STALLED
    assert verdict.exit_code == 1
    assert "t=640" in verdict.message


def test_frozen_time_shorter_than_the_window_is_not_stalled():
    verdict = judge(status(), status(heartbeat=NOW + 179), seconds=179, now=NOW + 179)
    assert verdict.kind == Verdict.WATCHING
    assert verdict.exit_code == 0
    assert "unconfirmed" in verdict.message


def test_raid_clock_can_stay_frozen_longer_than_the_normal_run_window():
    first = status(raid=True)
    for seconds, expected in ((180, Verdict.WATCHING), (1200, Verdict.STALLED)):
        verdict = judge(first, status(raid=True, heartbeat=NOW + seconds), seconds=seconds, now=NOW + seconds)
        assert verdict.kind == expected


def test_entering_or_leaving_a_raid_resets_the_window():
    for raid in (True, False):
        second = status(raid=raid, heartbeat=NOW + 1200)
        assert judge(status(raid=not raid), second, seconds=1200, now=NOW + 1200).kind == Verdict.WATCHING


def test_new_run_with_lower_time_is_not_a_stall():
    current = status(t=25, heartbeat=NOW + 180, run_id="run-2")
    assert judge(status(), current, seconds=180, now=NOW + 180).kind == Verdict.WATCHING


def test_frozen_time_uses_supervisor_monotonic_age_despite_wall_clock_correction():
    active = ServiceState(StateKind.ACTIVE, "", session_id="afk-1", farmer_phase="run",
                          run_progress={"at_monotonic": MONOTONIC - 60, "clock_epoch": NOW - MONOTONIC,
                                        "window": 75, "pid": 42, "run_id": "run-1",
                                        "in_raid": False, "game_time": 640})
    waiting = judge(status(), status(heartbeat=NOW + 10), seconds=10, now=NOW + 10,
                    monotonic_now=MONOTONIC + 10, state=active)
    assert waiting.kind == Verdict.WATCHING
    assert "70 s" in waiting.message and "unconfirmed" not in waiting.message
    stalled = judge(status(), status(heartbeat=NOW + 14.5), seconds=15, now=NOW + 14.5,
                    monotonic_now=MONOTONIC + 15, state=active)
    assert stalled.kind == Verdict.STALLED


def test_old_supervisor_evidence_does_not_carry_into_the_next_attempt():
    active = ServiceState(StateKind.ACTIVE, "", session_id="afk-1", farmer_phase="run",
                          run_progress={"at_monotonic": MONOTONIC - 600, "clock_epoch": NOW - MONOTONIC,
                                        "window": 180, "pid": 999, "run_id": "run-1",
                                        "in_raid": False, "game_time": 640})
    verdict = judge(status(), status(heartbeat=NOW + 15), seconds=15, now=NOW + 15,
                    monotonic_now=MONOTONIC + 15, state=active)
    assert verdict.kind == Verdict.WATCHING
    assert "unconfirmed" in verdict.message


def test_unmatched_boot_clock_is_not_used_as_supervisor_evidence():
    active = ServiceState(StateKind.ACTIVE, "", session_id="afk-1", farmer_phase="run",
                          run_progress={"at_monotonic": MONOTONIC - 600, "clock_epoch": NOW - MONOTONIC - 3600,
                                        "window": 180, "pid": 42, "run_id": "run-1",
                                        "in_raid": False, "game_time": 640})
    verdict = judge(status(), status(heartbeat=NOW + 15), seconds=15, now=NOW + 15,
                    monotonic_now=MONOTONIC + 15, state=active)
    assert verdict.kind == Verdict.WATCHING
    assert "unconfirmed" in verdict.message


def test_old_heartbeat_means_the_farmer_is_not_running():
    old = status(heartbeat=NOW - 16)
    verdict = judge(old, old, seconds=0, now=NOW)
    assert verdict.kind == Verdict.NOT_RUNNING
    assert verdict.exit_code == 2


def test_health_uses_the_live_supervisors_configured_heartbeat_timeout():
    active = ServiceState(StateKind.ACTIVE, "", session_id="afk-1", farmer_phase="paused",
                          heartbeat_stale_after=4.5)
    paused = status(phase="paused", heartbeat=NOW - 5)
    assert judge(paused, paused, seconds=0, now=NOW, state=active).kind == Verdict.NOT_RUNNING
    assert judge(paused, paused, seconds=0, now=NOW).kind == Verdict.PAUSED


def test_missing_status_means_the_farmer_is_not_running():
    verdict = judge(None, None, seconds=15, now=NOW)
    assert verdict.kind == Verdict.NOT_RUNNING
    assert verdict.exit_code == 2


def test_a_run_that_ends_between_samples_is_moving_not_stalled():
    verdict = judge(status(), status(phase="settle", heartbeat=NOW + 15), seconds=15, now=NOW + 15)
    assert verdict.kind == Verdict.BETWEEN_RUNS
    assert verdict.exit_code == 0


def test_settle_keep_and_maintenance_are_between_runs():
    for phase in ("settle", "keep", "maint", "idle"):
        same = status(phase=phase, heartbeat=NOW + 15)
        assert judge(same, same, seconds=15, now=NOW + 15).kind == Verdict.BETWEEN_RUNS


def test_operator_pause_and_finished_sessions_are_reported_as_such():
    paused = status(phase="paused", heartbeat=NOW + 15)
    assert judge(paused, paused, seconds=15, now=NOW + 15).kind == Verdict.PAUSED
    done = status(phase="done", heartbeat=NOW - 600)
    verdict = judge(done, done, seconds=15, now=NOW + 15)
    assert verdict.kind == Verdict.FINISHED
    assert verdict.exit_code == 0


def test_cli_reports_frozen_time_without_calling_a_short_sample_stalled(tmp_path):
    profile = make_profile(godot_root(tmp_path), "Midgard Survivors")
    frozen = status(heartbeat=4_000_000_000.0)  # Fresh for the whole test.
    (profile / "farmer_status.json").write_text(json.dumps(frozen))
    env = dict(os.environ, XDG_DATA_HOME=str(tmp_path), APPDATA=str(tmp_path), LOCALAPPDATA=str(tmp_path))

    result = subprocess.run([sys.executable, "-m", "midgard_farm.health", "--seconds", "0.2"],
                            env=env, capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    assert "WATCHING" in result.stdout and "t=640" in result.stdout


def test_cli_uses_fresh_service_evidence_without_waiting_for_a_second_sample(tmp_path, monkeypatch):
    for name in ("XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path))
    profile = make_profile(godot_root(tmp_path), "Midgard Survivors")
    now = time.time()
    monotonic = time.monotonic()
    (profile / "farmer_status.json").write_text(json.dumps(status(heartbeat=now)))
    directory = platform.current().app_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text(json.dumps({
        "kind": "active", "updated_at": now, "refresh_interval": 10,
        "session_id": "afk-1", "farmer_phase": "run",
        "run_progress": {"at_monotonic": monotonic, "clock_epoch": now - monotonic,
                         "window": 0, "pid": 42, "run_id": "run-1",
                         "in_raid": False, "game_time": 640},
    }))

    result = subprocess.run([sys.executable, "-m", "midgard_farm.health", "--seconds", "60"],
                            capture_output=True, text=True, timeout=20)

    assert result.returncode == 1, result.stderr
    assert "STALLED" in result.stdout and "unconfirmed" not in result.stdout
