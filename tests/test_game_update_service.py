"""Drive update recovery through real service commands, state and history files."""

import json
import signal
import sys
from pathlib import Path

import pytest

from midgard_farm.core import commands, game_update
from midgard_farm.core.history import read_history
from midgard_farm.core.state import StateKind, read_state

from test_game_update import SAVE_CODE, UpdateFarm, farmer_sources, snapshot
from test_profile import godot_root, make_profile
from test_supervisor import Farm, wait_for
from test_platform import lock_freed_within


RUNNER = [sys.executable, str(Path(__file__).with_name("fake_update_service.py"))]


@pytest.fixture
def update_service(tmp_path, monkeypatch):
    home = tmp_path / "Godot data"
    for name in ("XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(home))
    profile = make_profile(godot_root(home), "Game Profile")
    update = UpdateFarm(tmp_path, profile, monkeypatch)
    sources = tmp_path / "app farmer sources"
    farmer_sources(sources)
    desktop = tmp_path / "desktop.jsonl"
    plan = tmp_path / "plan.txt"
    plan.write_text("clean:goal\n", encoding="utf-8")
    preset = tmp_path / "preset.json"
    preset.write_text("{}", encoding="utf-8")
    for name, path in (("FAKE_GAME_PROFILE", profile), ("FAKE_SUPERVISED_PLAN", plan),
                       ("FAKE_FARMER_SOURCES", sources), ("FAKE_DESKTOP_TRACE", desktop)):
        monkeypatch.setenv(name, str(path))
    return Farm(update.os, profile, preset, plan), update, sources, desktop


def test_game_update_night_waits_rebuilds_and_runs_one_attempt(update_service):
    farm, update, _, desktop = update_service
    original = snapshot(update.patches)
    original_save = (farm.profile / "profile.json").read_bytes()
    update.running.touch()
    request = farm.start()
    with farm.service(runner=RUNNER, max_failures=1):
        waiting = wait_for(lambda: read_state(farm.os_),
                           lambda state: state.kind is StateKind.WAITING_FOR_GAME)
        assert waiting.reason == "waiting for the game to close"
        assert snapshot(update.patches) == original
        assert (farm.profile / "profile.json").read_bytes() == original_save
        assert not update.observations()
        assert not farm.plan.with_suffix(".count").exists()
        update.running.unlink()
        outcome, _ = farm.outcome()
        wait_for(lambda: farm.notifications() == ["goal"])
        wait_for(lambda: desktop.exists() and b"Midgard farmer: goal" in desktop.read_bytes())
        assert not request.exists()
        wait_for(lambda: read_state(farm.os_).last_outcome)
    assert outcome["kind"] == "finished" and outcome["reason"] == "goal"
    assert len(outcome["attempts"]) == 1 and outcome["attempts"][0]["number"] == 1
    assert farm.plan.with_suffix(".count").read_text() == "1"
    assert [entry["stage"] for entry in update.observations()] == ["build", "smoke"]
    smoke_run = json.loads((update.records / "attempt-1.json").read_bytes())
    assert "farmer_supervisor.lock" not in smoke_run["stale_files"]
    updated, farmed = read_history(farm.os_)
    assert updated["kind"] == "game_update" and updated["outcome"] == "ready"
    assert farmed["kind"] == "session" and farmed["outcome"] == "finished"
    assert json.loads((update.patches / "state.json").read_bytes())["file"] == "patch_farmer.pck"
    assert {json.loads(line)["title"]: json.loads(line)["priority"] for line in desktop.read_bytes().splitlines()} == {
        "Midgard farmer: goal": "normal",
    }


@pytest.mark.parametrize("lift", ["check_again", "official_sha", "farmer_hash"])
def test_service_refuses_start_until_retry_block_is_lifted(update_service, monkeypatch, lift):
    farm, update, sources, desktop = update_service
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["failed", "no_wins", "pass"]')
    with farm.service(runner=RUNNER):
        failure = wait_for(lambda: read_state(farm.os_), lambda state: state.quarantine is not None)
        assert failure.kind is StateKind.FARMER_UNAVAILABLE
        assert failure.quarantine["reason"] == "smoke_failed"
        wait_for(lambda: desktop.exists() and desktop.read_bytes().endswith(b"\n"))
        assert failure.quarantine["next_action"] == "Check again"
        assert failure.quarantine["attempts"] == []
        assert Path(failure.quarantine["log_path"]).is_file()
        assert json.loads((update.patches / "state.json").read_bytes())["file"] == "official.pck"
        assert (farm.profile / "profile.json").read_bytes() == b'{"zeny":100}'
    assert [json.loads(line)["priority"] for line in desktop.read_bytes().splitlines()] == ["high"]

    with farm.service(runner=RUNNER):
        request = farm.start()
        refusal = commands.rejection_path(farm.os_, request)
        assert wait_for(lambda: json.loads(farm.os_.read_shared(refusal)))["reason"] == "smoke_failed"
        assert not farm.plan.with_suffix(".count").exists()
        assert [entry["stage"] for entry in update.observations()] == ["build", "smoke", "smoke"]
        assert len(read_history(farm.os_)) == 1
        if lift == "check_again":
            update.running.touch()
            command = commands.submit(farm.os_, "check_again")
            wait_for(lambda: not command.exists())
            waiting = read_state(farm.os_)
            assert waiting.kind is StateKind.WAITING_FOR_GAME and waiting.quarantine is None
            queued_start = farm.start()
            wait_for(lambda: not queued_start.exists())
            assert not commands.rejection_path(farm.os_, queued_start).exists()
            update.running.unlink()
            outcome, _ = farm.outcome()
            assert outcome["kind"] == "finished" and len(outcome["attempts"]) == 1
            wait_for(lambda: read_state(farm.os_).last_outcome)
            assert read_state(farm.os_).quarantine is None
            wait_for(lambda: farm.notifications() == ["goal"])
            failed, rebuilt, farmed = read_history(farm.os_)
            assert failed["outcome"] == "quarantine" and rebuilt["outcome"] == "ready"
            assert failed["official_patch_sha256"] == rebuilt["official_patch_sha256"]
            assert failed["farmer_hash"] == rebuilt["farmer_hash"]
            assert farmed["kind"] == "session"
            assert [entry["stage"] for entry in update.observations()] == ["build", "smoke", "smoke", "build", "smoke"]
            return
        elif lift == "official_sha":
            update.publish_official(save_code=SAVE_CODE + "# new official patch bytes\n")
        if lift != "farmer_hash":
            wait_for(lambda: read_history(farm.os_), lambda events: len(events) == 2)
    if lift == "farmer_hash":
        with (sources / "src/farmer.gd").open("a", encoding="utf-8") as script:
            script.write("\n# new farmer input\n")
    with farm.service(runner=RUNNER):
        wait_for(lambda: read_history(farm.os_), lambda events: len(events) == 2)
        farm.start()
        outcome, _ = farm.outcome()
        wait_for(lambda: read_state(farm.os_).last_outcome)
        wait_for(lambda: desktop.exists() and b"Midgard farmer: goal" in desktop.read_bytes())
        assert read_state(farm.os_).quarantine is None
    assert outcome["kind"] == "finished" and len(outcome["attempts"]) == 1
    failed, rebuilt, farmed = read_history(farm.os_)
    assert failed["outcome"] == "quarantine" and rebuilt["outcome"] == "ready"
    assert (failed["official_patch_sha256"] != rebuilt["official_patch_sha256"]) is (lift == "official_sha")
    assert (failed["farmer_hash"] != rebuilt["farmer_hash"]) is (lift == "farmer_hash")
    assert farmed["kind"] == "session"
    assert "Midgard farmer: game_update_handled" not in desktop.read_text(encoding="utf-8")
    assert [entry["stage"] for entry in update.observations()] == ["build", "smoke", "smoke", "build", "smoke"]


def test_pending_start_quarantines_at_once_without_attempting_after_smoke_failure(update_service, monkeypatch):
    farm, update, _, _ = update_service
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["failed", "no_wins"]')
    update.running.touch()
    request = farm.start()
    with farm.service(runner=RUNNER, max_failures=1):
        wait_for(lambda: read_state(farm.os_),
                 lambda state: state.session_id is not None and state.kind is StateKind.WAITING_FOR_GAME)
        assert not request.exists()
        update.running.unlink()
        outcome, directory = farm.outcome()
        unavailable = wait_for(lambda: read_state(farm.os_), lambda state: state.last_outcome)
        assert unavailable.kind is StateKind.FARMER_UNAVAILABLE
        assert unavailable.quarantine["next_action"] == "Check again"
        wait_for(lambda: farm.notifications() == ["smoke_failed"])
    assert (outcome["kind"], outcome["reason"], outcome["attempts"]) == ("quarantined", "smoke_failed", [])
    quarantine = json.loads((directory / "quarantine.json").read_bytes())
    assert quarantine["attempts"] == [] and Path(quarantine["log_path"]).is_file()
    assert not farm.plan.with_suffix(".count").exists()
    assert [row["kind"] for row in read_history(farm.os_)] == ["game_update", "session"]


def test_update_before_a_restart_does_not_count_as_an_attempt(update_service, monkeypatch):
    farm, update, _, _ = update_service
    farm.plan.write_text("crash\nclean:goal\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["pass", "pass"]')
    with farm.service(runner=RUNNER, max_failures=2, backoff_base=2, backoff_max=2):
        wait_for(lambda: read_history(farm.os_), lambda history: len(history) == 1)
        farm.start()
        wait_for(lambda: read_state(farm.os_), lambda state: state.reason.startswith("Restarting in"))
        update.publish_official(save_code=SAVE_CODE + "# second update\n", version="3")
        outcome, _ = farm.outcome()
        wait_for(lambda: read_state(farm.os_).last_outcome)
        wait_for(lambda: farm.notifications() == ["fail", "game_update_handled", "goal"])
    assert outcome["kind"] == "finished"
    assert [(item["number"], item["outcome"]) for item in outcome["attempts"]] == [(1, "failed"), (2, "finished")]
    assert [entry["stage"] for entry in update.observations()] == ["build", "smoke", "build", "smoke"]
    assert [row["kind"] for row in read_history(farm.os_)] == ["game_update", "game_update", "session"]


def test_check_again_is_refused_during_a_live_afk_attempt(update_service):
    farm, update, _, _ = update_service
    farm.plan.write_text("commands\n", encoding="utf-8")
    with farm.service(runner=RUNNER):
        farm.start()
        farm.status("run")
        request = commands.submit(farm.os_, "check_again")
        refusal = commands.rejection_path(farm.os_, request)
        assert wait_for(lambda: json.loads(farm.os_.read_shared(refusal))) == {
            "command": "check_again", "reason": "AFK session running",
        }
        wait_for(lambda: any(item["request"] == request.name for item in read_state(farm.os_).command_refusals))
        commands.submit(farm.os_, "finish")
        outcome, _ = farm.outcome()
    assert (outcome["kind"], outcome["reason"]) == ("finished", "finish")
    assert [entry["stage"] for entry in update.observations()] == ["build", "smoke"]


def test_missing_state_after_binding_reports_reinstall_without_automatic_work(update_service):
    farm, update, _, _ = update_service
    with farm.service(runner=RUNNER):
        wait_for(lambda: read_history(farm.os_))
        state_path = update.patches / "state.json"
        state_path.unlink()
        request = farm.start()
        refusal = commands.rejection_path(farm.os_, request)
        assert wait_for(lambda: json.loads(farm.os_.read_shared(refusal)))["reason"] == (
            "start the game and accept the update"
        )
        state = read_state(farm.os_)
        assert state.kind is StateKind.FARMER_UNAVAILABLE and state.reason == "start the game and accept the update"
        assert read_history(farm.os_)[-1]["classification"] == "game_reinstall"
        assert not state_path.exists() and not farm.plan.with_suffix(".count").exists()
    assert [entry["stage"] for entry in update.observations()] == ["build", "smoke"]


@pytest.mark.parametrize("reason", ["build_failed", "anchors_broken"])
def test_startup_build_failures_publish_named_high_priority_quarantine(update_service, monkeypatch, reason):
    farm, update, _, desktop = update_service
    if reason == "anchors_broken":
        update.publish_official(save_code="missing upstream anchor\n")
    else:
        monkeypatch.setenv("FAKE_GDRE_DROP_RESOURCE", "res://scripts/autoload/save.gdc")
    with farm.service(runner=RUNNER):
        state = wait_for(lambda: read_state(farm.os_), lambda value: value.quarantine is not None)
        assert state.kind is StateKind.FARMER_UNAVAILABLE and state.reason == reason
        assert state.quarantine["next_action"] == "Check again" and state.quarantine["attempts"] == []
        assert Path(state.quarantine["log_path"]).is_file()
        wait_for(lambda: desktop.exists() and desktop.read_bytes().endswith(b"\n"))
    row, = read_history(farm.os_)
    assert row["kind"] == "game_update" and row["reason"] == reason
    assert json.loads(desktop.read_bytes()) == {"priority": "high", "title": f"Midgard farmer: {reason}"}
    assert not farm.plan.with_suffix(".count").exists()


@pytest.mark.parametrize("mounted", [False, True])
def test_missing_named_official_pack_refuses_start_without_quarantine(update_service, mounted):
    farm, update, _, _ = update_service
    if mounted:
        assert isinstance(update.pipeline().run(), game_update.Ready)
    (update.patches / "official.pck").unlink()
    with farm.service(runner=RUNNER):
        request = farm.start()
        refusal = commands.rejection_path(farm.os_, request)
        assert wait_for(lambda: json.loads(farm.os_.read_shared(refusal)), seconds=3)["reason"] == (
            "start the game and accept the update"
        )
        state = read_state(farm.os_)
        assert state.kind is StateKind.FARMER_UNAVAILABLE and state.quarantine is None
        assert not list(farm.data.glob("logs/supervisor-*/outcome.json"))


@pytest.mark.parametrize("resume", ["start", "check_again"])
def test_restore_official_stays_restored_while_idle_and_across_service_restart(update_service, resume):
    farm, update, _, _ = update_service
    original_profile = (farm.profile / "profile.json").read_bytes()
    with farm.service(runner=RUNNER):
        wait_for(lambda: read_history(farm.os_), lambda rows: rows and rows[-1]["outcome"] == "ready")
        state = wait_for(lambda: read_state(farm.os_), lambda state: state.kind is StateKind.IDLE)
        assert state.game_update_classification == "current"
        request = commands.submit(farm.os_, "restore_official")
        wait_for(lambda: read_state(farm.os_).last_restore,
                 lambda result: result and result["request"] == request.name)
        state = wait_for(lambda: read_state(farm.os_),
                         lambda state: state.game_update_classification == "farmer_removed_or_stale")
        assert state.last_restore["outcome"] == "restored"
        assert state.kind is StateKind.IDLE
        assert (update.patches / "state.json").read_bytes() == (update.patches / "official-state.json").read_bytes()
        assert not (update.patches / "patch_farmer.pck").exists()
        assert (farm.profile / "profile.json").read_bytes() == original_profile
        row = read_history(farm.os_)[-1]
        assert (row["kind"], row["action"], row["outcome"]) == ("game_update", "restore_official", "restored")
    with farm.service(runner=RUNNER):
        # A second successful restore after startup also exercises the idle command loop.
        request = commands.submit(farm.os_, "restore_official")
        wait_for(lambda: read_state(farm.os_).last_restore,
                 lambda result: result and result["request"] == request.name)
        assert not (update.patches / "patch_farmer.pck").exists()
        assert [row["outcome"] for row in read_history(farm.os_)] == ["ready", "restored", "restored"]
        if resume == "start":
            farm.start()
            outcome, _ = farm.outcome()
            assert outcome["kind"] == "finished"
        else:
            request = commands.submit(farm.os_, "check_again")
            wait_for(lambda: not request.exists())
            assert not farm.plan.with_suffix(".count").exists()
        assert not read_state(farm.os_).keep_official
    assert json.loads((update.patches / "state.json").read_bytes())["file"] == "patch_farmer.pck"
    assert [entry["stage"] for entry in update.observations()] == ["build", "smoke"]


def test_restore_official_reports_missing_official_file_without_touching_profile(update_service):
    farm, update, _, _ = update_service
    with farm.service(runner=RUNNER):
        wait_for(lambda: read_history(farm.os_))
        (update.patches / "official.pck").unlink()
        before = snapshot(update.patches)
        request = commands.submit(farm.os_, "restore_official")
        result = wait_for(lambda: read_state(farm.os_).last_restore,
                          lambda result: result and result["request"] == request.name)
        assert result["outcome"] == "official_patch_missing"
        assert result["reason"] == "start the game and accept the update"
        assert read_state(farm.os_).game_update_classification == "game_reinstall"
        row = next(row for row in read_history(farm.os_) if row.get("action") == "restore_official")
        assert row["reason"] == result["reason"]
        assert snapshot(update.patches) == before


@pytest.mark.parametrize("busy", ["game", "attempt", "backoff", "waiting"])
def test_restore_official_refuses_while_game_or_session_is_active(update_service, busy):
    farm, update, _, _ = update_service
    farm.plan.write_text("crash\n" if busy == "backoff" else "commands\n", encoding="utf-8")
    with farm.service(runner=RUNNER, backoff_base=30.0, backoff_max=30.0):
        wait_for(lambda: read_history(farm.os_))
        if busy in ("game", "waiting"):
            update.running.touch()
        if busy != "game":
            farm.start()
            if busy == "backoff":
                wait_for(lambda: read_state(farm.os_).reason, lambda reason: reason.startswith("Restarting"))
            elif busy == "waiting":
                wait_for(lambda: read_state(farm.os_),
                         lambda state: state.session_id and state.kind is StateKind.WAITING_FOR_GAME)
            else:
                farm.status("run")
        before = snapshot(update.patches)
        request = commands.submit(farm.os_, "restore_official")
        refusal = commands.rejection_path(farm.os_, request)
        reason = "Close the game before restoring the official patch." if busy == "game" else "AFK session running"
        assert wait_for(lambda: json.loads(farm.os_.read_shared(refusal))) == {
            "command": "restore_official", "reason": reason,
        }
        wait_for(lambda: any(row["request"] == request.name for row in read_state(farm.os_).command_refusals))
        assert snapshot(update.patches) == before
        assert not any(row.get("action") == "restore_official" for row in read_history(farm.os_))
        if busy != "game":
            commands.submit(farm.os_, "finish")
            farm.outcome()


@pytest.mark.skipif(sys.platform != "linux", reason="exercise the service's SIGTERM handler")
def test_service_stop_cancels_smoke_and_can_resume_without_rebuilding(update_service, monkeypatch):
    farm, update, _, _ = update_service
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["hang", "pass"]')
    original = (update.patches / "state.json").read_bytes()
    with farm.service(runner=RUNNER) as proc:
        wait_for(lambda: (update.records / "grandchild.ready").exists())
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=5) == 0
        assert lock_freed_within(update.records / "grandchild.lock", 5)
    assert (update.patches / "state.json").read_bytes() == original and not read_history(farm.os_)
    assert [entry["stage"] for entry in update.observations()] == ["build", "smoke"]

    with farm.service(runner=RUNNER):
        wait_for(lambda: read_state(farm.os_).kind is StateKind.IDLE and read_history(farm.os_))
    assert [entry["stage"] for entry in update.observations()] == ["build", "smoke", "smoke"]
    assert json.loads((update.patches / "state.json").read_bytes())["file"] == "patch_farmer.pck"


def test_active_update_gate_polls_game_at_most_once_a_second(update_service, monkeypatch, tmp_path):
    farm, update, _, _ = update_service
    poll_trace = tmp_path / "game-polls"
    monkeypatch.setenv("FAKE_UPDATE_POLL_TRACE", str(poll_trace))
    update.running.touch()

    with farm.service(runner=RUNNER):
        farm.start()
        wait_for(lambda: read_state(farm.os_),
                 lambda state: state.kind is StateKind.WAITING_FOR_GAME and state.session_id is not None)
        # Skip the event-driven startup and Start checks, then observe periodic checks.
        lines = wait_for(lambda: farm.os_.read_shared(poll_trace).splitlines(), lambda rows: len(rows) >= 6)
        assert not update.observations()

    stamps = [float(row) for row in lines[-3:]]
    assert all(later - earlier >= 0.99 for earlier, later in zip(stamps, stamps[1:]))
