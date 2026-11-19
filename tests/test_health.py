"""`python -m midgard_farm.health`: is the farm actually making progress?

2026-11-19 night: the heartbeat stayed fresh and the phase said `run` for 6.5 h
while the run's own time sat at t=640. Only comparing two samples tells
farming from stalled.
"""

import json
import os
import subprocess
import sys

from midgard_farm.health import Verdict, judge

from test_profile import godot_root, make_profile

NOW = 1_800_000_000.0


def status(phase="run", t=640.0, kills=13_557, zeny=27_000_000, runs=4, heartbeat=NOW):
    return {"phase": phase, "heartbeat": heartbeat,
            "game": {"time": t, "kills": kills}, "totals": {"zeny": zeny, "runs": runs}}


def test_run_time_advancing_is_farming():
    verdict = judge(status(), status(t=655.0, kills=13_700, heartbeat=NOW + 15), seconds=15, now=NOW + 15)
    assert verdict.kind == Verdict.FARMING
    assert verdict.exit_code == 0
    assert "+143 kills" in verdict.message


def test_fresh_heartbeat_with_frozen_run_time_is_stalled():
    verdict = judge(status(), status(heartbeat=NOW + 15), seconds=15, now=NOW + 15)
    assert verdict.kind == Verdict.STALLED
    assert verdict.exit_code == 1
    assert "t=640" in verdict.message


def test_old_heartbeat_means_the_farmer_is_not_running():
    old = status(heartbeat=NOW - 120)
    verdict = judge(old, old, seconds=15, now=NOW + 15)
    assert verdict.kind == Verdict.NOT_RUNNING
    assert verdict.exit_code == 2


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


def test_cli_reports_a_stall_on_the_found_profile(tmp_path):
    profile = make_profile(godot_root(tmp_path), "Midgard Survivors")
    frozen = status(heartbeat=4_000_000_000.0)  # Fresh for the whole test.
    (profile / "farmer_status.json").write_text(json.dumps(frozen))
    env = dict(os.environ, XDG_DATA_HOME=str(tmp_path), APPDATA=str(tmp_path), LOCALAPPDATA=str(tmp_path))

    result = subprocess.run([sys.executable, "-m", "midgard_farm.health", "--seconds", "0.2"],
                            env=env, capture_output=True, text=True, timeout=30)

    assert result.returncode == 1, result.stderr
    assert "STALLED" in result.stdout
