import json
import time

import pytest

from midgard_farm import platform
from midgard_farm.core.state import StateKind, StateReporter, read_state, state_path


def test_state_refreshes_during_work_and_expires_after_service_stops(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    assert read_state(os_).kind is StateKind.STALE
    with StateReporter(os_, refresh_interval=0.1) as reporter:
        assert read_state(os_).kind is StateKind.IDLE
        assert read_state(os_).refresh_interval == 0.1
        assert json.loads(os_.read_shared(state_path(os_)))["refresh_interval"] == 0.1
        reporter.set(StateKind.WAITING_FOR_GAME, "Close the game", session_id="afk-test")
        waiting = read_state(os_)
        assert (waiting.kind, waiting.reason, waiting.session_id) == (
            StateKind.WAITING_FOR_GAME, "Close the game", "afk-test")
        reporter.set(StateKind.REBUILDING, "Smoking the farmer patch")
        rebuilding = read_state(os_)
        deadline = time.monotonic() + 2
        while read_state(os_).updated_at == rebuilding.updated_at:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert read_state(os_).session_id == "afk-test"
        reporter.set(StateKind.UPDATING, "Installing app version v2")
        assert read_state(os_).kind is StateKind.UPDATING
        reporter.set(StateKind.FARMER_UNAVAILABLE, "Cannot smoke the farmer patch",
                     quarantine={"reason": "smoke_failed", "detail": "No wins"})
        assert read_state(os_).quarantine["next_action"] == "Check again"

    # Age the persisted publication without waiting for wall-clock time.
    path = state_path(os_)
    saved = json.loads(path.read_bytes())
    saved["updated_at"] = time.time() - 60
    saved["future_field"] = {"new": True}
    os_.write_atomic(path, json.dumps(saved).encode())
    stale = read_state(os_)
    assert stale.kind is StateKind.STALE
    assert stale.session_id == "afk-test"


@pytest.mark.parametrize(("offset", "interval", "expected_interval", "kind"), [
    (1.5, 1, 1, StateKind.IDLE),
    (4, 1, 1, StateKind.STALE),
    (-31, 3600, 10, StateKind.STALE),
    (0, 0.00001, 0.1, StateKind.IDLE),
])
def test_state_reader_bounds_reported_refresh_and_tolerates_small_clock_skew(
    tmp_path, monkeypatch, offset, interval, expected_interval, kind,
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    path = state_path(os_)
    path.parent.mkdir(parents=True)
    os_.write_atomic(path, json.dumps({"v": 1, "kind": "idle", "reason": "",
                                     "updated_at": time.time() + offset, "refresh_interval": interval}).encode())
    state = read_state(os_)
    assert state.refresh_interval == expected_interval
    assert state.kind is kind
