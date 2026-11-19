"""Supervisor decisions, driven through a fake farmer child (no game)."""
import dataclasses
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from supervisor import Policy, Supervisor, make_notifier  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_farmer.py"

FAST = Policy(
    heartbeat_interval=0.1,
    stale_intervals=3,
    startup_grace=2.0,
    backoff_base=0.05,
    backoff_max=0.2,
    max_failures=3,
    failure_window=60.0,
    kill_grace=1.0,
)


@pytest.fixture
def farm(tmp_path):
    def make(*plan, policy=FAST):
        plan_file = tmp_path / "plan.txt"
        plan_file.write_text("\n".join(plan))
        status = tmp_path / "farmer_status.json"
        sent = []
        sup = Supervisor(
            command=[sys.executable, str(FAKE), str(status), str(plan_file)],
            status_path=status,
            log_dir=tmp_path / "logs",
            policy=policy,
            notify=lambda event, message: sent.append(event),
        )
        return sup, sent, plan_file

    return make


def test_clean_finish_is_not_restarted(farm):
    sup, sent, _ = farm("clean:max_runs", "crash")

    result = sup.run()

    assert result.kind == "finished"
    assert result.reason == "max_runs"
    assert len(result.attempts) == 1
    assert sent == ["stop"]


def test_goal_finish_notifies_goal(farm):
    sup, sent, _ = farm("clean:goal")

    assert sup.run().reason == "goal"
    assert sent == ["goal"]


def test_crash_restarts_with_exponential_backoff(farm):
    sup, sent, _ = farm("crash", "fail:settle_timeout", "clean:stop")

    started = time.monotonic()
    result = sup.run()

    assert time.monotonic() - started >= 0.15  # the 0.05 + 0.1 backoff was slept
    assert result.kind == "finished"
    assert [a.outcome for a in result.attempts] == ["failed", "failed", "finished"]
    assert [a.reason for a in result.attempts][:2] == ["exit_1_phase_run", "settle_timeout"]
    assert [a.delay for a in result.attempts] == [0.0, 0.05, 0.1]
    assert sent == ["fail", "fail", "stop"]


def test_silent_exit_without_terminal_status_is_a_failure(farm):
    sup, _, _ = farm("exit:0", "clean:stop")

    result = sup.run()

    assert result.attempts[0].outcome == "failed"
    assert result.attempts[0].reason == "exit_0_no_status"
    assert result.kind == "finished"


def test_status_left_from_before_the_attempt_is_ignored(farm):
    sup, _, _ = farm("exit:0", "clean:stop")
    sup.status_path.write_text(json.dumps({"phase": "done", "terminal": True, "heartbeat_seq": 9}))
    old = time.time_ns() - 10**9
    os.utime(sup.status_path, ns=(old, old))

    result = sup.run()

    assert result.attempts[0].reason == "exit_0_no_status"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie is dead for our purposes; /proc may vanish once it is reaped.
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def test_stale_heartbeat_kills_the_whole_group_and_restarts(farm):
    sup, sent, plan = farm("hang", "clean:stop")

    started = time.monotonic()
    result = sup.run()

    assert result.attempts[0].reason == "heartbeat_stale"
    assert result.kind == "finished"
    assert time.monotonic() - started < 3  # 3 x 0.1s stale, not the 2s startup grace
    grandchild = int(plan.with_suffix(".grandchild").read_text())
    assert not _alive(grandchild)
    assert sent == ["fail", "stop"]


def test_repeated_failures_in_window_quarantine(farm):
    sup, sent, _ = farm("crash")

    result = sup.run()

    assert result.kind == "quarantined"
    assert len(result.attempts) == FAST.max_failures
    assert sent == ["fail", "fail", "quarantine"]
    report = json.loads((result.log_dir / "quarantine.json").read_text())
    assert report["last_failure"] == "exit_1_phase_run"
    assert (result.log_dir / "attempt-03.status.json").exists()


def test_failures_outside_window_do_not_quarantine(farm):
    policy = dataclasses.replace(FAST, failure_window=0.0)
    sup, _, _ = farm("crash", "crash", "crash", "crash", "clean:stop", policy=policy)

    result = sup.run()

    assert result.kind == "finished"
    assert len(result.attempts) == 5


@pytest.mark.parametrize("step,reason", [
    ("exit:78", "preflight_failed"),
    ("fail:cfg_invalid", "cfg_invalid"),
    ("fail:checkpoint_corrupt", "checkpoint_corrupt"),
])
def test_fatal_preflight_or_config_quarantines_without_retry(farm, step, reason):
    sup, sent, _ = farm(step, "clean:stop")

    result = sup.run()

    assert result.kind == "quarantined"
    assert result.reason == reason
    assert len(result.attempts) == 1
    assert sent == ["quarantine"]


def test_operator_stop_kills_the_group_and_does_not_restart(farm):
    sup, sent, plan = farm("hang")
    threading.Timer(0.5, sup.request_stop).start()

    result = sup.run()

    assert result.kind == "stopped"
    assert len(result.attempts) == 1
    grandchild = int(plan.with_suffix(".grandchild").read_text())
    assert not _alive(grandchild)
    assert sent == ["stop"]


def test_operator_stop_during_backoff_does_not_restart(farm):
    policy = dataclasses.replace(FAST, backoff_base=30.0, backoff_max=30.0)
    sup, sent, _ = farm("crash", "clean:stop", policy=policy)
    threading.Timer(0.5, sup.request_stop).start()

    started = time.monotonic()
    result = sup.run()

    assert time.monotonic() - started < 5
    assert result.kind == "stopped"
    assert len(result.attempts) == 1
    assert sent == ["fail", "stop"]


def test_unresponsive_ntfy_does_not_block_the_supervisor(monkeypatch):
    monkeypatch.setenv("PATH", "")  # no notify-send: no desktop popup from tests
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()  # never accepted: the request hangs until its timeout
        notify = make_notifier(f"http://127.0.0.1:{server.getsockname()[1]}/topic")

        started = time.monotonic()
        notify("fail", "test")

        assert time.monotonic() - started < 0.5
