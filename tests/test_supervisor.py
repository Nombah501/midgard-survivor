"""Legacy supervisor scenarios exercised through the background service and a fake game."""

import hashlib
import json
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from midgard_farm import platform
from midgard_farm.core import commands, patch_info
from midgard_farm.core.history import append_event, read_history
from midgard_farm.core.state import StateKind, read_state
from midgard_farm.core.backup import known_good_snapshot, publish_known_good

from test_profile import godot_root, make_profile


SERVICE = [sys.executable, str(Path(__file__).with_name("fake_notification_service.py"))]
FAKE = Path(__file__).with_name("fake_supervised_game.py")
POSIX = pytest.mark.skipif(sys.platform != "linux", reason="Linux process signals and permissions")


def wait_for(read, predicate=bool, *, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = read()
            if predicate(result):
                return result
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(0.01)
    pytest.fail(f"condition not reached: {read}")


@dataclass
class Farm:
    os_: platform.Platform
    profile: Path
    preset: Path
    plan: Path
    prefix: list[str]

    @property
    def data(self):
        return self.os_.app_data_dir()

    @property
    def status_path(self):
        return self.profile / "farmer_status.json"

    def status(self, phase):
        return wait_for(lambda: json.loads(self.os_.read_shared(self.status_path)), lambda d: d["phase"] == phase)

    def send(self, command, **fields):
        queue = self.data / "commands"
        queue.mkdir(parents=True, exist_ok=True)
        path = queue / f"{time.time_ns():020d}-{uuid.uuid4().hex}.json"
        self.os_.write_atomic(path, json.dumps({"command": command, **fields}).encode())
        return path

    def start(self):
        return self.send("start", character={"class": "archer", "job_path": 1}, preset=str(self.preset))

    def outcome(self):
        def read():
            paths = list(self.data.glob("logs/supervisor-*/outcome.json"))
            if paths:
                path = paths[0]
                return json.loads(self.os_.read_shared(path)), path.parent
        return wait_for(read)

    @contextmanager
    def service(self, **policy):
        timing = dict(heartbeat_interval=0.15, startup_grace=3.0, backoff_base=0.05,
                      backoff_max=0.2, max_failures=3, failure_window=60.0,
                      kill_grace=0.5, stop_grace=0.85) | policy
        command = [*self.prefix, *SERVICE]
        env = {**os.environ, "FAKE_SERVICE_POLICY": json.dumps(timing)}
        output = self.plan.with_suffix(".output")
        with output.open("wb") as log:
            proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env)
            try:
                yield proc
            finally:
                if proc.poll() is None:
                    if sys.platform == "linux":
                        self.stop(proc)
                    else:
                        self.send("finish")
                        time.sleep(0.15)
                        proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)

    def stop(self, proc):
        if self.prefix:
            children = Path(f"/proc/{proc.pid}/task/{proc.pid}/children")
            child, = wait_for(lambda: children.read_text().split())
            os.kill(int(child), signal.SIGTERM)
        else:
            proc.send_signal(signal.SIGTERM)

    def host_pid(self, proc, game_pid):
        if not self.prefix:
            return game_pid

        def find(parent):
            for child in Path(f"/proc/{parent}/task/{parent}/children").read_text().split():
                pid = int(child)
                for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                    if line.startswith("NSpid:") and int(line.split()[-1]) == game_pid:
                        return pid
                if match := find(pid):
                    return match
            return None

        return wait_for(lambda: find(proc.pid))

    def notifications(self):
        return [line.split()[2].rstrip(":") for line in self.plan.with_suffix(".output").read_text(
            encoding="utf-8").splitlines() if line.startswith("supervisor: notify ")]


@pytest.fixture
def farm(tmp_path, monkeypatch):
    # Use real process, lock and atomic-write implementations. Only the game is fake.
    home = tmp_path / "home data"
    game_dir = tmp_path / "game install"
    game_dir.mkdir()
    for name in ("FARMER_SESSION_ID", "FARMER_BACKUP_DIR", "FARMER_DISPLAY", "FARMER_MIN_FREE_MB"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    monkeypatch.setenv("APPDATA", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("GAME_DIR", str(game_dir))
    os_ = platform.current()
    profile = make_profile(godot_root(home), "Renamed Midgard Survivors")
    monkeypatch.setenv("FAKE_GAME_PROFILE", str(profile))
    plan = tmp_path / "plan.txt"
    monkeypatch.setenv("FAKE_SUPERVISED_PLAN", str(plan))
    (profile / "patches/state.json").write_text('{"file":"patch_farmer.pck"}')
    (profile / "patches/patch_official.pck").write_bytes(b"official")
    (profile / "patches/patch_farmer.pck").write_bytes(b"farmer")
    patch_info.save(os_, patch_info.info_path(os_), patch_info.PatchInfo(
        patch_file="patch_official.pck", patch_version="1", patch_sha256=hashlib.sha256(b"official").hexdigest(),
        bridge_file="bridge.pck", bridge_sha256="", bytecode="ebc36a7", farmer_api=1,
        farmer_hash="fixture", result_sha256=hashlib.sha256(b"farmer").hexdigest(), built_at="fixture",
    ))
    preset = tmp_path / "farmer preset.json"
    game = os_.game_executable()
    prefix = []
    if sys.platform == "win32":
        # A real PE image lets the test exercise the Job Object. The copied
        # interpreter runs the game via sitecustomize, with no Godot flags.
        shutil.copyfile(Path(sys.base_prefix) / "python.exe", game)
        for dll in Path(sys.base_prefix).glob("*.dll"):
            shutil.copyfile(dll, game_dir / dll.name)
        monkeypatch.setenv("PYTHONHOME", sys.base_prefix)
        monkeypatch.setenv("PATH", str(Path(sys.base_prefix)) + os.pathsep + os.environ["PATH"])
        monkeypatch.setenv("PYTHONPATH", str(game_dir) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        (game_dir / "sitecustomize.py").write_text(
            "import os, sys\nfrom pathlib import Path\n"
            f"if Path(sys.executable).name.lower() == {game.name.lower()!r}:\n"
            f"    exec(compile(Path({str(FAKE)!r}).read_bytes(), {str(FAKE)!r}, 'exec'))\n"
        )
    else:
        game.write_bytes(f"#!{sys.executable}\n".encode() + FAKE.read_bytes())
        game.chmod(0o755)
        # Never signal or mask the operator's game; isolate the fake service.
        if os_.game_running():
            unshare = shutil.which("unshare")
            if unshare is None:
                pytest.skip("cannot isolate the fake service from the live game")
            prefix = [unshare, "--user", "--map-current-user", "--mount", "--pid", "--fork", "--mount-proc",
                      "--kill-child", "--"]
            if subprocess.run([*prefix, "true"], capture_output=True).returncode:
                pytest.skip("cannot isolate the fake service from the live game")
    preset.write_text(json.dumps({"stage": "payon", "danger": 12, "class": "thief",
                                  "display": sys.platform == "win32", "builds": {"class": "mage",
                                  "archer": {"job_path": 0, "skills": ["agi"]}}}))
    return Farm(os_, profile, preset, plan, prefix)


def plan_game(farm, *steps):
    if sys.platform == "linux":
        unshare = shutil.which("unshare")
        if unshare is None or subprocess.run([*farm.prefix, unshare, "-cn", "--", "true"], capture_output=True).returncode:
            pytest.skip("real network namespace unavailable")
    farm.plan.write_text("\n".join(steps))


def test_clean_finish_uses_character_and_preset_without_restart(farm):
    plan_game(farm, "clean:max_runs", "crash")
    with farm.service():
        farm.start()
        outcome, directory = farm.outcome()
    assert (outcome["kind"], outcome["reason"]) == ("finished", "max_runs")
    assert len(outcome["attempts"]) == 1
    assert (directory / "attempt-01.log").is_file()
    assert farm.notifications() == ["stop"]
    assert farm.plan.with_suffix(".count").read_text() == "1"
    config = json.loads((farm.profile / "farmer.cfg").read_bytes())
    assert (config["stage"], config["danger"], config["class"]) == ("payon", 12, "archer")
    assert config["job_paths"]["archer"] == 1
    assert config["builds"] == {"archer": {"job_path": 1, "skills": ["agi"]}}
    assert json.loads(farm.preset.read_bytes())["class"] == "thief"


def test_goal_finish_notifies_goal(farm):
    plan_game(farm, "clean:goal")
    with farm.service():
        commands.submit(farm.os_, commands.Start(commands.Character("archer", 1), farm.preset))
        outcome, _ = farm.outcome()
    assert (outcome["kind"], outcome["reason"]) == ("finished", "goal")
    assert farm.notifications() == ["goal"]


@pytest.mark.parametrize("command", ["finish", "abort"])
def test_operator_terminal_command_notifies_stop_without_restart(farm, command):
    plan_game(farm, "commands", "crash")
    with farm.service():
        farm.start()
        farm.status("run")
        request = farm.send(command)
        outcome, _ = farm.outcome()
        assert not request.exists()
        assert not (farm.profile / "farmer_command").exists()
    assert (outcome["kind"], outcome["reason"]) == ("finished", command)
    assert len(outcome["attempts"]) == 1
    assert farm.notifications() == ["stop"]
    assert (known_good_snapshot(farm.data / "backups") is not None) == (command == "finish")


def test_paused_heartbeat_is_healthy_and_resume_keeps_the_child(farm):
    plan_game(farm, "commands", "crash")
    with farm.service():
        farm.start()
        running = farm.status("run")
        farm.send("pause")
        paused = farm.status("paused")
        wait_for(lambda: json.loads(farm.os_.read_shared(farm.status_path)), lambda d: (
            d["phase"] == "paused" and d["heartbeat_seq"] >= paused["heartbeat_seq"] + 12
        ))
        farm.send("resume")
        resumed = farm.status("run")
        farm.send("finish")
        outcome, _ = farm.outcome()
    assert running["pid"] == paused["pid"] == resumed["pid"]
    assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("finished", "finish", 1)
    assert farm.notifications() == ["stop"]


@POSIX
@pytest.mark.parametrize("step", ["commands", "commands:preboot", "commands:no-exit"])
def test_supervisor_stop_requests_finish_before_signalling_child(farm, step):
    plan_game(farm, step, "crash")
    with farm.service() as proc:
        farm.start()
        if step.endswith("preboot"):
            wait_for(farm.plan.with_suffix(".preboot").exists)
            assert not farm.status_path.exists()
        else:
            farm.status("run")
        farm.stop(proc)
        outcome, _ = farm.outcome()
        assert proc.wait(timeout=5) == 0
    if step.endswith("no-exit"):
        assert (outcome["kind"], outcome["reason"]) == ("stopped", "no_exit_after_terminal")
        # A valid done status existed, but supervisor had to force-stop the child.
        assert farm.status("done")["finish_reason"] == "finish"
        assert known_good_snapshot(farm.data / "backups") is None
    else:
        assert (outcome["kind"], outcome["reason"]) == ("finished", "finish")
        assert known_good_snapshot(farm.data / "backups") is not None
    assert len(outcome["attempts"]) == 1
    assert farm.notifications() == ["stop"]


def test_crash_restarts_with_exponential_backoff_and_same_session_id(farm):
    plan_game(farm, "crash", "fail:settle_timeout", "clean:stop")
    with farm.service():
        started = time.monotonic()
        farm.start()
        outcome, logs = farm.outcome()
    assert time.monotonic() - started >= 0.15
    assert outcome["kind"] == "finished"
    attempts = outcome["attempts"]
    assert [attempt["outcome"] for attempt in attempts] == ["failed", "failed", "finished"]
    assert [attempt["reason"] for attempt in attempts] == ["exit_1_phase_run", "settle_timeout", "stop"]
    assert [attempt["delay"] for attempt in attempts] == [0.0, 0.05, 0.1]
    assert farm.notifications() == ["fail", "fail", "stop"]
    assert all(json.loads(path.read_bytes())["session"] == outcome["session"]
               for path in (logs / "attempt-01.status.json", logs / "attempt-02.status.json"))
    assert farm.status("done")["session"] == outcome["session"]


@pytest.mark.parametrize("old_status", [False, True])
def test_silent_exit_is_not_a_finish_even_if_old_status_says_done(farm, old_status):
    plan_game(farm, "exit:0", "clean:stop")
    if old_status:
        farm.status_path.write_text('{"phase":"done","terminal":true,"heartbeat_seq":9}')
        old = time.time_ns() - 10**9
        os.utime(farm.status_path, ns=(old, old))
    with farm.service():
        farm.start()
        outcome, _ = farm.outcome()
    assert outcome["attempts"][0]["reason"] == "exit_0_no_status"
    assert (outcome["kind"], len(outcome["attempts"])) == ("finished", 2)


def _alive(pid):
    if sys.platform == "win32":
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                capture_output=True, text=True, check=True)
        return f'","{pid}","' in result.stdout
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def test_stale_heartbeat_kills_the_whole_group_and_restarts(farm):
    plan_game(farm, "hang", "clean:stop")
    with farm.service() as proc:
        started = time.monotonic()
        farm.start()
        pid = int(wait_for(lambda: farm.plan.with_suffix(".grandchild").read_text()))
        grandchild = farm.host_pid(proc, pid)
        outcome, _ = farm.outcome()
    assert outcome["attempts"][0]["reason"] == "heartbeat_stale"
    assert outcome["kind"] == "finished"
    assert time.monotonic() - started < 3  # stale window, not the startup grace
    wait_for(lambda: not _alive(grandchild))
    assert farm.notifications() == ["fail", "stop"]


@POSIX
def test_sigstopped_farmer_is_a_stale_heartbeat_and_restarts(farm):
    plan_game(farm, "commands", "clean:stop")
    with farm.service() as proc:
        farm.start()
        running = farm.host_pid(proc, farm.status("run")["pid"])
        os.kill(running, signal.SIGSTOP)
        outcome, _ = farm.outcome()
    assert outcome["attempts"][0]["reason"] == "heartbeat_stale"
    assert not _alive(running)
    assert (outcome["kind"], len(outcome["attempts"])) == ("finished", 2)
    assert farm.notifications() == ["fail", "stop"]


def test_startup_grace_without_first_heartbeat(farm):
    plan_game(farm, "no-heartbeat", "clean:stop")
    with farm.service(startup_grace=0.6):
        farm.start()
        outcome, _ = farm.outcome()
    assert outcome["attempts"][0]["reason"] == "no_heartbeat"
    assert (outcome["kind"], len(outcome["attempts"])) == ("finished", 2)


def test_unreadable_status_is_never_a_clean_finish(farm):
    plan_game(farm, "garbage", "clean:stop")
    with farm.service():
        farm.start()
        outcome, _ = farm.outcome()
    assert outcome["attempts"][0]["outcome"] == "failed"
    assert outcome["attempts"][0]["reason"] == "exit_0_phase_run"
    assert farm.notifications() == ["fail", "stop"]


@pytest.mark.parametrize("step", ["missing-terminal", "foreign-session"])
def test_done_requires_an_explicit_terminal_status_from_this_session(farm, step):
    plan_game(farm, f"{step}:goal", "clean:stop")
    with farm.service():
        farm.start()
        outcome, _ = farm.outcome()
    assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("finished", "stop", 2)
    assert farm.notifications() == ["fail", "stop"]


def test_reliable_exit_code_can_veto_a_done_status_but_windows_ignores_it(farm):
    plan_game(farm, "done-bad-exit:goal", "clean:stop")
    with farm.service():
        farm.start()
        outcome, _ = farm.outcome()
    if sys.platform == "win32":
        assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("finished", "goal", 1)
        assert farm.notifications() == ["goal"]
    else:
        assert outcome["attempts"][0]["reason"] == "exit_9_phase_done"
        assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("finished", "stop", 2)


@POSIX
def test_terminal_status_allows_the_games_expected_headless_sigkill(farm):
    plan_game(farm, "done-sigkill:goal")
    with farm.service():
        farm.start()
        outcome, _ = farm.outcome()
    assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("finished", "goal", 1)
    assert known_good_snapshot(farm.data / "backups") is not None


@pytest.mark.parametrize("legacy_lock", [False, True])
def test_second_supervisor_leaves_the_running_session_alone(farm, legacy_lock):
    session = farm.data / "session.json"
    session.write_text("afk-first")
    lock_path = farm.profile / "farmer_supervisor.lock" if legacy_lock else farm.data / "service.lock"
    with farm.os_.acquire_lock(lock_path):
        second = subprocess.run([*farm.prefix, *SERVICE], capture_output=True,
                                encoding="utf-8", timeout=5)
    assert second.returncode == 75, second.stdout + second.stderr
    assert "another supervisor" in second.stderr
    assert session.read_text() == "afk-first"
    assert not (farm.profile / "farmer_stop").exists()
    assert "attempt" not in second.stdout


@POSIX
def test_unwritable_profile_quarantines_the_supervisor_itself(farm):
    if os.geteuid() == 0:
        pytest.skip("root can write a read-only directory")
    farm.profile.chmod(0o555)
    try:
        result = subprocess.run([*farm.prefix, *SERVICE], capture_output=True,
                                encoding="utf-8", timeout=5)
    finally:
        farm.profile.chmod(0o755)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "notify quarantine: profile directory unusable" in result.stdout
    assert "attempt" not in result.stdout


def test_preflight_quarantine_names_the_actual_launcher_cause(farm):
    (farm.profile / "patches/patch_official.pck").write_bytes(b"next patch")
    with farm.service() as proc:
        farm.start()
        outcome, directory = farm.outcome()
        state = wait_for(lambda: read_state(farm.os_), lambda state: state.kind is StateKind.IDLE and state.quarantine)
        history = read_history(farm.os_)
        assert proc.poll() is None  # Still available to the window after quarantine.
    cause = "run: official patch changed (game updated); rebuild the farmer patch"
    report = json.loads((directory / "quarantine.json").read_bytes())
    assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("quarantined", "preflight_failed", 1)
    assert report["detail"] == cause
    assert state.quarantine["reason"] == "preflight_failed"
    assert state.quarantine["detail"] == cause
    assert state.quarantine["next_action"] == "Start a new session"
    assert state.last_outcome == outcome
    assert len(history) == 1 and history[0]["outcome"] == "quarantined"
    assert history[0]["totals"]["runs"] == 0
    assert cause in (directory / "attempt-01.log").read_text()
    assert not farm.plan.with_suffix(".count").exists()
    assert farm.notifications() == ["quarantine"]


@POSIX
def test_isolation_exit_78_quarantines_without_launch_or_retry(farm, monkeypatch):
    monkeypatch.setenv("PATH", str(farm.data))
    with farm.service():
        farm.start()
        outcome, directory = farm.outcome()
    assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("quarantined", "preflight_failed", 1)
    assert outcome["attempts"][0]["exit_code"] == 78
    assert "network isolation" in json.loads((directory / "quarantine.json").read_bytes())["detail"]
    assert not farm.plan.with_suffix(".count").exists()
    assert farm.notifications() == ["quarantine"]


@pytest.mark.parametrize("detail", ["", "preset failed launcher preflight"])
def test_returned_exit_78_quarantines_without_retry(farm, monkeypatch, detail):
    plan_game(farm, "exit:78", "clean:stop")
    monkeypatch.setenv("FAKE_PREFLIGHT_DETAIL", detail)
    with farm.service():
        farm.start()
        outcome, directory = farm.outcome()
    assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("quarantined", "preflight_failed", 1)
    assert outcome["attempts"][0]["exit_code"] == 78
    report = json.loads((directory / "quarantine.json").read_bytes())
    assert report["detail"] == (f"run: {detail}" if detail else "run: attempt exited 78 without a preflight message")
    assert farm.plan.with_suffix(".count").read_text() == "1"
    assert farm.notifications() == ["quarantine"]


def test_repeated_failures_in_window_quarantine(farm):
    plan_game(farm, "crash")
    with farm.service():
        farm.start()
        outcome, directory = farm.outcome()
    assert outcome["kind"] == "quarantined"
    assert len(outcome["attempts"]) == 3
    assert farm.notifications() == ["fail", "fail", "quarantine"]
    report = json.loads((directory / "quarantine.json").read_bytes())
    assert report["last_failure"] == "exit_1_phase_run"
    assert (directory / "attempt-03.status.json").exists()


def test_failures_outside_window_do_not_quarantine(farm):
    plan_game(farm, "crash", "crash", "crash", "crash", "clean:stop")
    with farm.service(failure_window=0.0):
        farm.start()
        outcome, _ = farm.outcome()
    assert (outcome["kind"], len(outcome["attempts"])) == ("finished", 5)


@pytest.mark.parametrize("reason", ["cfg_invalid", "checkpoint_corrupt"])
def test_fatal_farmer_status_quarantines_without_retry(farm, reason):
    plan_game(farm, f"fail:{reason}", "clean:stop")
    with farm.service():
        farm.start()
        outcome, _ = farm.outcome()
    assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("quarantined", reason, 1)
    assert farm.notifications() == ["quarantine"]


@POSIX
def test_supervised_forced_stop_kills_the_group_without_replacing_known_good(farm):
    plan_game(farm, "hang", "clean:stop")
    backups = farm.data / "backups"
    publish_known_good(farm.os_, farm.profile, backups)
    previous = known_good_snapshot(backups)
    assert previous is not None
    (farm.profile / "profile.json").write_text("changed before stop")
    with farm.service(stale_intervals=30) as proc:
        farm.start()
        pid = int(wait_for(lambda: farm.plan.with_suffix(".grandchild").read_text()))
        grandchild = farm.host_pid(proc, pid)
        started = time.monotonic()
        farm.stop(proc)
        outcome, _ = farm.outcome()
        assert proc.wait(timeout=5) == 0
    assert time.monotonic() - started >= 0.85
    assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("stopped", "operator_timeout", 1)
    assert outcome["attempts"][0]["exit_code"] == -signal.SIGKILL
    assert (farm.profile / "farmer_stop").exists()
    assert not _alive(grandchild)
    assert farm.notifications() == ["stop"]
    assert known_good_snapshot(backups) == previous
    assert (previous / "profile.json").read_text() == "{}"


@POSIX
def test_operator_stop_during_backoff_does_not_restart(farm):
    plan_game(farm, "crash", "clean:stop")
    with farm.service(backoff_base=30.0, backoff_max=30.0) as proc:
        farm.start()
        wait_for(farm.notifications, lambda events: events == ["fail"])
        started = time.monotonic()
        farm.stop(proc)
        outcome, _ = farm.outcome()
        assert proc.wait(timeout=5) == 0
    assert time.monotonic() - started < 5
    assert (outcome["kind"], len(outcome["attempts"])) == ("stopped", 1)
    assert farm.notifications() == ["fail", "stop"]


def test_unresponsive_ntfy_does_not_block_the_service(farm, monkeypatch):
    plan_game(farm, "crash", "clean:stop")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(5)
        url = f"http://127.0.0.1:{server.getsockname()[1]}/topic"
        (farm.data / "config.json").write_text(json.dumps({"ntfy_url": url}))
        with farm.service():
            farm.start()
            try:
                conn, _ = server.accept()
                conn.settimeout(5)
                with conn, conn.makefile("rb") as request:
                    assert request.readline().startswith(b"POST /topic HTTP/")
                    headers = []
                    while (line := request.readline()) != b"\r\n":
                        assert line
                        headers.append(line.lower())
                    assert b"title: midgard farmer: fail\r\n" in headers
                    assert b"priority: 3\r\n" in headers
                    # Don't answer before the game retry and outcome are complete.
                    outcome, _ = farm.outcome()
                    assert (outcome["kind"], len(outcome["attempts"])) == ("finished", 2)
            finally:
                server.close()


@POSIX
def test_printed_systemd_unit_starts_the_service_with_a_shutdown_budget(farm, tmp_path):
    result = subprocess.run([*SERVICE, "--print-unit"], check=True, capture_output=True,
                            encoding="utf-8", timeout=5)
    unit = result.stdout
    assert "KillMode=mixed\n" in unit
    assert "TimeoutStopSec=90\n" in unit
    assert "Restart=on-failure\n" in unit
    command = shlex.split(next(line.removeprefix("ExecStart=") for line in unit.splitlines()
                               if line.startswith("ExecStart=")))
    (farm.profile / "patches/patch_farmer.pck").unlink()
    fake_bin = tmp_path / "notification-bin"
    fake_bin.mkdir()
    fake_notify = fake_bin / "notify-send"
    fake_notify.write_text("#!/bin/sh\nexit 0\n")
    fake_notify.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    with subprocess.Popen([*farm.prefix, *command], stdout=subprocess.DEVNULL, env=env) as proc:
        try:
            farm.start()
            outcome, _ = farm.outcome()
            assert outcome["reason"] == "preflight_failed"
        finally:
            farm.stop(proc)
            assert proc.wait(timeout=5) == 0


def test_crash_recovery_reuses_session_without_replaying_the_start(farm):
    (farm.profile / "patches/patch_farmer.pck").unlink()
    start = {"character": {"class": "archer", "job_path": 1}, "preset": str(farm.preset)}
    request = farm.send("start", **start)
    session_id = "afk-" + uuid.uuid4().hex
    (farm.data / "session.json").write_text(json.dumps({
        "id": session_id, "start": {"command": "start", **start}, "request": request.name,
        "profile": str(farm.profile),
    }))
    with farm.service():
        outcome, _ = farm.outcome()
        wait_for(lambda: not request.exists())
    assert outcome["session"] == session_id
    assert len(list(farm.data.glob("logs/supervisor-*"))) == 1
    assert farm.notifications() == ["quarantine"]


def test_duplicate_start_is_refused_but_start_after_queued_finish_runs(farm):
    plan_game(farm, "commands:delay-terminal", "clean:goal")
    with farm.service():
        farm.start()
        current = farm.status("run")["session"]
        command = commands.Start(commands.Character("archer", 1), farm.preset)
        duplicate = commands.submit(farm.os_, command)
        finish = farm.send("finish")
        next_start = commands.submit(farm.os_, command)

        def read_outcomes():
            return [json.loads(farm.os_.read_shared(path)) for path in farm.data.glob("logs/supervisor-*/outcome.json")]

        outcomes = wait_for(read_outcomes, lambda values: len(values) == 2)
        assert not duplicate.exists() and not finish.exists() and not next_start.exists()
    refusal = json.loads(commands.rejection_path(farm.os_, duplicate).read_bytes())
    assert refusal == {"command": "start", "reason": "AFK session already active"}
    assert not (farm.data / "command-rejections" / next_start.name).exists()
    by_reason = {outcome["reason"]: outcome for outcome in outcomes}
    assert by_reason["finish"]["session"] == current
    assert by_reason["goal"]["session"] != current
    assert all(outcome["kind"] == "finished" and len(outcome["attempts"]) == 1 for outcome in outcomes)


def test_startup_quarantine_preserves_corrupt_session_and_accepts_start_in_same_service(farm):
    plan_game(farm, "clean:goal")
    marker = farm.data / "session.json"
    corrupt = b"\xffbroken session"
    marker.write_bytes(corrupt)
    current = farm.data / "quarantine.json"
    with farm.service() as proc:
        idle_command = farm.send("pause")
        wait_for(lambda: not idle_command.exists(), seconds=4)
        assert proc.poll() is None
        assert not farm.plan.with_suffix(".count").exists()
        assert farm.notifications() == ["quarantine"]
        record = json.loads(farm.os_.read_shared(current))
        assert record["reason"] == "invalid_saved_session"
        state = read_state(farm.os_)
        assert state.kind is StateKind.IDLE
        assert state.quarantine == {**record, "next_action": "Start a new session"}
        assert not marker.exists()
        diagnostics = farm.data / record["diagnostics"]
        assert (diagnostics / "session.json").read_bytes() == corrupt
        farm.start()
        outcome, _ = farm.outcome()
    assert (outcome["kind"], outcome["reason"]) == ("finished", "goal")
    assert not current.exists()
    assert (diagnostics / "session.json").read_bytes() == corrupt
    assert json.loads((diagnostics / "quarantine.json").read_bytes()) == record


def test_duplicate_start_rejections_keep_only_the_newest_twenty(farm):
    plan_game(farm, "commands")
    with farm.service():
        farm.start()
        farm.status("run")
        command = commands.Start(commands.Character("archer", 1), farm.preset)
        duplicates = [commands.submit(farm.os_, command) for _ in range(23)]
        farm.send("finish")
        farm.outcome()
        state = read_state(farm.os_)
    rejections = [commands.rejection_path(farm.os_, request) for request in duplicates]
    assert set(rejections[-20:]) == set(rejections[0].parent.glob("*.json"))
    assert {row["request"] for row in state.command_refusals} == {path.name for path in rejections[-20:]}


def test_service_publishes_live_farmer_and_one_history_row_with_session_totals(farm):
    plan_game(farm, "commands:summary")
    with farm.service():
        farm.start()
        active = wait_for(lambda: read_state(farm.os_), lambda state: state.farmer_phase == "run")
        assert active.kind is StateKind.ACTIVE
        assert active.session_id == farm.status("run")["session"]
        assert active.last_heartbeat > 0
        farm.send("finish")
        idle = wait_for(lambda: read_state(farm.os_), lambda state: state.kind is StateKind.IDLE and state.last_outcome)
        assert idle.session_id is None
        assert idle.last_outcome["session"] == active.session_id
        row, = read_history(farm.os_)
        assert row["session_id"] == active.session_id and row["outcome"] == "finished"
        assert row["totals"] == {"started": 2, "runs": 1, "wins": 1, "losses": 0, "lost": 1,
                                 "zeny": 7200, "xp": 50, "kills": 40, "coins": 3, "ymir": 2,
                                 "wall_s": 1800, "cards_gain": 2, "materials": {"ore": 4}}


@pytest.mark.parametrize("already_appended", [False, True])
def test_recovering_committed_outcome_adds_history_only_if_missing(farm, already_appended):
    session_id = "afk-" + uuid.uuid4().hex
    request = farm.start()
    (farm.data / "session.json").write_text(json.dumps({
        "id": session_id, "start": json.loads(request.read_bytes()),
        "request": request.name, "profile": str(farm.profile),
    }))
    directory = farm.data / "logs" / f"supervisor-{session_id}"
    directory.mkdir(parents=True)
    (directory / "outcome.json").write_text(json.dumps({
        "session": session_id, "kind": "stopped", "reason": "operator", "attempts": [], "totals": {"runs": 2},
    }))
    if already_appended:
        append_event(farm.os_, "session", session_id=session_id, outcome="stopped", totals={"runs": 2})

    with farm.service():
        state = wait_for(lambda: read_state(farm.os_), lambda state: state.last_outcome)
        assert state.last_outcome["session"] == session_id
        row, = read_history(farm.os_)
        assert row["totals"] == {"runs": 2}
    assert not farm.plan.with_suffix(".count").exists()
