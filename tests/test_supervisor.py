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
from types import SimpleNamespace

import pytest

from midgard_farm import platform
from midgard_farm.core import commands, launch, patch_info, supervisor
from midgard_farm.core.history import append_event, history_path, read_history
from midgard_farm.core.state import StateKind, read_state
from midgard_farm.core.backup import known_good_snapshot, publish_known_good
from midgard_farm.core.farmer_patch import farmer_hash

from test_profile import godot_root, make_profile


SERVICE = [sys.executable, str(Path(__file__).with_name("fake_notification_service.py"))]
FAKE = Path(__file__).with_name("fake_supervised_game.py")
POSIX = pytest.mark.skipif(sys.platform != "linux", reason="Linux process signals and permissions")


def wait_for(read, predicate=bool, *, seconds=20):
    # Generous: a passing test returns as soon as the condition holds; the
    # budget only bounds a real failure, and windows-latest runs slowly.
    deadline = time.monotonic() + seconds
    last: object = "<nothing read>"
    while time.monotonic() < deadline:
        try:
            last = read()
            if predicate(last):
                return last
        except (FileNotFoundError, ValueError) as exc:
            last = exc
        time.sleep(0.01)
    pytest.fail(f"condition not reached: {read}; last read: {last!r}")


@dataclass
class Farm:
    os_: platform.Platform
    profile: Path
    preset: Path
    plan: Path

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
        return self.send("start", character={"class": "archer", "job_path": 1}, preset=str(self.preset),
                         settings={"location": "payon", "difficulty": 12})

    def outcome(self):
        def read():
            paths = list(self.data.glob("logs/supervisor-*/outcome.json"))
            if paths:
                path = paths[0]
                return json.loads(self.os_.read_shared(path)), path.parent
        return wait_for(read)

    @contextmanager
    def service(self, *, runner=SERVICE, **policy):
        # The fake publishes every 0.05 s; keep its accelerated watchdog
        # independent from individual heartbeat writes.
        timing = dict(heartbeat_interval=0.5, startup_grace=3.0, backoff_base=0.05,
                      backoff_max=0.2, max_failures=3, failure_window=60.0,
                      kill_grace=0.5, stop_grace=0.85) | policy
        stop = self.plan.with_suffix(".service-stop")
        stop.unlink(missing_ok=True)
        env = {**os.environ, "FAKE_SERVICE_POLICY": json.dumps(timing), "FAKE_SERVICE_STOP": str(stop)}
        output = self.plan.with_suffix(".output")
        with output.open("wb") as log:
            proc = subprocess.Popen(runner, stdout=log, stderr=subprocess.STDOUT, env=env)
            try:
                yield proc
            except BaseException as exc:
                logs = sorted(self.data.glob("logs/supervisor-*/attempt-*.log"))
                for path in [output, *logs]:
                    exc.add_note(f"{path.name}:\n{path.read_text(encoding='utf-8', errors='replace')}")
                raise
            finally:
                if proc.poll() is None:
                    stop.touch()
                    try:
                        assert proc.wait(timeout=5) == 0, output.read_text(encoding="utf-8", errors="replace")
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                        raise

    def notifications(self):
        return [line.split()[2].rstrip(":") for line in self.plan.with_suffix(".output").read_text(
            encoding="utf-8").splitlines() if line.startswith("supervisor: notify ")]


@pytest.fixture
def farm(tmp_path, monkeypatch, service_game_platform):
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
    os_, startup = service_game_platform
    profile = make_profile(godot_root(home), "Renamed Midgard Survivors")
    monkeypatch.setenv("FAKE_GAME_PROFILE", str(profile))
    plan = tmp_path / "plan.txt"
    monkeypatch.setenv("FAKE_SUPERVISED_PLAN", str(plan))
    official_state = {"file": "patch_official.pck", "version": "1", "bridge": {"file": "bridge.pck"}}
    (profile / "patches/official-state.json").write_bytes(json.dumps(official_state).encode())
    (profile / "patches/state.json").write_bytes(
        json.dumps(official_state | {"file": "patch_farmer.pck", "farmer": 1}).encode(),
    )
    (profile / "patches/patch_official.pck").write_bytes(b"official")
    (profile / "patches/patch_farmer.pck").write_bytes(b"farmer")
    patch_info.save(os_, patch_info.info_path(os_), patch_info.PatchInfo(
        patch_file="patch_official.pck", patch_version="1", patch_sha256=hashlib.sha256(b"official").hexdigest(),
        bridge_file="bridge.pck", bridge_sha256="", bytecode="ebc36a7", farmer_api=1,
        farmer_hash=farmer_hash(), result_sha256=hashlib.sha256(b"farmer").hexdigest(), built_at="fixture",
    ))
    if sys.platform == "win32":
        # The fake is a python.exe, which rejects the Godot-only --headless flag.
        monkeypatch.setenv("FARMER_DISPLAY", "1")
    preset = tmp_path / "farmer preset.json"
    game = os_.game_executable()
    if sys.platform == "win32":
        # A real PE image lets the test exercise the Job Object. The copied
        # interpreter runs the game via sitecustomize, with no Godot flags.
        shutil.copyfile(Path(sys.base_prefix) / "python.exe", game)
        for dll in Path(sys.base_prefix).glob("*.dll"):
            shutil.copyfile(dll, game_dir / dll.name)
        monkeypatch.setenv("PYTHONHOME", sys.base_prefix)
        monkeypatch.setenv("PATH", str(Path(sys.base_prefix)) + os.pathsep + os.environ["PATH"])
        package_root = str(Path(platform.__file__).resolve().parents[2])
        monkeypatch.setenv("PYTHONPATH", os.environ["PYTHONPATH"] + os.pathsep + package_root)
        with startup.open("a", encoding="utf-8") as script:
            script.write(
                "import os, sys, traceback\nfrom pathlib import Path\n"
                f"if Path(sys.executable).name.lower() == {game.name.lower()!r}:\n"
                "    try:\n"
                f"        exec(compile(Path({str(FAKE)!r}).read_bytes(), {str(FAKE)!r}, 'exec'))\n"
                "    except Exception:\n"
                "        traceback.print_exc()\n"
                "        os._exit(1)\n"
            )
    else:
        game.write_bytes(f"#!{sys.executable}\n".encode() + FAKE.read_bytes())
        game.chmod(0o755)
    preset.write_text(json.dumps({"speed": 5,
                                  "builds": {"archer": {"job_path": 0, "skills": ["agi"]}}}))
    return Farm(os_, profile, preset, plan)


def plan_game(farm, *steps):
    if sys.platform == "linux":
        unshare = shutil.which("unshare")
        if unshare is None or subprocess.run([unshare, "-cn", "--", "true"], capture_output=True).returncode:
            pytest.skip("real network namespace unavailable")
    farm.plan.write_text("\n".join(steps))


@pytest.mark.parametrize(("location", "difficulty", "oaths"), [
    ("payon", 12, {}), ({"mode": "rotation"}, 30, {"tough": 2, "elite": 1}),
])
def test_clean_finish_uses_character_and_preset_without_restart(farm, location, difficulty, oaths):
    plan_game(farm, "clean:max_runs", "crash")
    with farm.service():
        farm.send("start", character={"class": "archer", "job_path": 1}, preset=str(farm.preset),
                  settings={"location": location, "difficulty": difficulty, "oaths": oaths,
                            "wishlist": ["sacred_excalibur", "gungnir"],
                            "upgrades": False, "card_fusion": False, "star_smith": True, "storage_cleanup": True,
                            "keep_unowned_legendaries": True})
        outcome, directory = farm.outcome()
    assert (outcome["kind"], outcome["reason"]) == ("finished", "max_runs")
    assert len(outcome["attempts"]) == 1
    assert (directory / "attempt-01.log").is_file()
    assert farm.notifications() == ["stop"]
    assert farm.plan.with_suffix(".count").read_text() == "1"
    config = json.loads((farm.profile / "farmer.cfg").read_bytes())
    assert (config["stage"], config["danger"], config["class"], config["oaths"]) == (location, difficulty, "archer", oaths)
    assert config["wishlist"] == ["sacred_excalibur", "gungnir"]
    assert config["keep_unowned_legendaries"] is True
    assert config["auto_upgrades"] is config["auto_sage"] is config["auto_fuse"] is False
    assert config["auto_potential"] is config["auto_storage_prune"] is True
    assert config["job_paths"]["archer"] == 1
    assert config["builds"] == {"archer": {"job_path": 1, "skills": ["agi"]}}
    assert json.loads(farm.preset.read_bytes())["speed"] == config["speed"] == 5


@pytest.mark.parametrize("settings", [
    [], {"location": [], "difficulty": 1}, {"location": True, "difficulty": 1},
    {"location": {}, "difficulty": 1}, {"location": {"mode": "random"}, "difficulty": 1},
    {"location": {"mode": "rotation", "id": "payon"}, "difficulty": 1},
    {"location": None, "difficulty": True}, {"location": None},
])
def test_malformed_start_and_resume_are_refused(farm, settings):
    with farm.service():
        for command in ("start", "resume"):
            request = farm.send(command, character={"class": "archer", "job_path": 1}, preset=str(farm.preset),
                                settings=settings)
            rejection = commands.rejection_path(farm.os_, request)
            row = wait_for(lambda: json.loads(farm.os_.read_shared(rejection)))
            assert row["command"] == command and "settings" in row["reason"]
    assert not (farm.profile / "farmer.cfg").exists()


@pytest.mark.parametrize("oaths", [None, ["tough"], {"": 1}, {"tough": "1"}, {"tough": True}, {"tough": 1.5}, {"tough": 0}])
def test_malformed_oath_ranks_are_refused(farm, oaths):
    with farm.service():
        for command in ("start", "resume"):
            request = farm.send(command, character={"class": "archer", "job_path": 1}, preset=str(farm.preset),
                                settings={"location": "prontera", "difficulty": 30, "oaths": oaths})
            rejection = commands.rejection_path(farm.os_, request)
            row = wait_for(lambda: json.loads(farm.os_.read_shared(rejection)))
            assert row["command"] == command and "settings.oaths" in row["reason"]
    assert not (farm.profile / "farmer.cfg").exists()


@pytest.mark.parametrize("wishlist", [None, "gungnir", {"gungnir": True}, [1], [True], [" "], ["a\0b"], ["a", "a"]])
def test_malformed_wishlists_are_refused(farm, wishlist):
    with farm.service():
        for command in ("start", "resume"):
            request = farm.send(command, character={"class": "archer", "job_path": 1}, preset=str(farm.preset),
                                settings={"location": None, "difficulty": None, "wishlist": wishlist})
            rejection = commands.rejection_path(farm.os_, request)
            row = wait_for(lambda: json.loads(farm.os_.read_shared(rejection)))
            assert row["command"] == command and "settings.wishlist" in row["reason"]
    assert not (farm.profile / "farmer.cfg").exists()


@pytest.mark.parametrize(("key", "value"), [
    ("upgrades", 0), ("card_fusion", "false"), ("star_smith", None), ("storage_cleanup", []),
    ("show_game_window", "true"), ("keep_unowned_legendaries", 1),
])
def test_non_boolean_session_switches_are_refused(farm, key, value):
    with farm.service():
        for command in ("start", "resume"):
            request = farm.send(command, character={"class": "archer", "job_path": 1}, preset=str(farm.preset),
                                settings={"location": None, "difficulty": None, key: value})
            rejection = commands.rejection_path(farm.os_, request)
            row = wait_for(lambda: json.loads(farm.os_.read_shared(rejection)))
            assert row["command"] == command and f"settings.{key}" in row["reason"]
    assert not (farm.profile / "farmer.cfg").exists()


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


@pytest.mark.parametrize("structured", [False, True])
def test_paused_heartbeat_is_healthy_and_resume_keeps_the_child(farm, structured):
    plan_game(farm, "commands", "crash")
    with farm.service(run_stall_window=0.75):
        farm.start()
        running = farm.status("run")
        farm.send("pause")
        paused = farm.status("paused")
        wait_for(lambda: json.loads(farm.os_.read_shared(farm.status_path)), lambda d: (
            d["phase"] == "paused" and d["heartbeat"] - paused["heartbeat"] >= 0.9
        ))
        if structured:
            farm.send("resume", settings={"location": {"mode": "rotation"}, "difficulty": 30, "oaths": {"tough": 3},
                                          "wishlist": ["gungnir"], "upgrades": False, "card_fusion": False,
                                          "star_smith": True, "storage_cleanup": True, "show_game_window": True,
                                          "keep_unowned_legendaries": True})
        else:
            farm.send("resume")
        resumed = farm.status("run")
        config = json.loads((farm.profile / "farmer.cfg").read_bytes())
        assert (config["stage"], config["danger"], config["oaths"]) == (
            ({"mode": "rotation"}, 30, {"tough": 3}) if structured else ("payon", 12, {}))
        assert config["wishlist"] == (["gungnir"] if structured else [])
        assert config["keep_unowned_legendaries"] is structured
        assert config["auto_upgrades"] is config["auto_sage"] is config["auto_fuse"] is (not structured)
        assert config["auto_potential"] is config["auto_storage_prune"] is structured
        assert config["display"] is (sys.platform == "win32")  # Resume did not relaunch the game.
        assert config["class"] == "archer" and config["job_paths"] == {"archer": 1}
        saved = json.loads((farm.data / "session.json").read_bytes())
        assert saved["start"]["settings"] == {
            "location": config["stage"], "difficulty": config["danger"], "oaths": config["oaths"],
            "wishlist": config["wishlist"],
            "upgrades": not structured, "card_fusion": not structured,
            "star_smith": structured, "storage_cleanup": structured,
            "show_game_window": structured,
            "keep_unowned_legendaries": structured,
        }
        wait_for(lambda: json.loads(farm.os_.read_shared(farm.status_path)), lambda d: (
            d["phase"] == "run" and d["pid"] == running["pid"] and d["heartbeat_seq"] >= resumed["heartbeat_seq"] + 3
        ))
        farm.send("finish")
        outcome, _ = farm.outcome()
    assert running["pid"] == paused["pid"] == resumed["pid"]
    assert (outcome["kind"], outcome["reason"], len(outcome["attempts"])) == ("finished", "finish", 1)
    assert farm.notifications() == ["stop"]


@POSIX
def test_pending_watch_mode_is_used_by_the_restarted_game(farm):
    plan_game(farm, "commands:exit-on-resume", "done-sigabrt:max_runs")
    with farm.service():
        farm.start()
        farm.status("run")
        assert json.loads((farm.profile / "farmer.cfg").read_bytes())["display"] is False
        farm.send("pause")
        farm.status("paused")
        commands.submit(farm.os_, commands.Resume(commands.SessionSettings(show_game_window=True)))
        outcome, _ = farm.outcome()
    assert json.loads((farm.profile / "farmer.cfg").read_bytes())["display"] is True
    assert (outcome["kind"], outcome["reason"]) == ("finished", "max_runs")
    assert [attempt["outcome"] for attempt in outcome["attempts"]] == ["failed", "finished"]


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
        proc.send_signal(signal.SIGTERM)
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing violation")
def test_fake_game_retries_status_replacement(tmp_path, monkeypatch):
    import ctypes
    import runpy

    from midgard_farm.platform import windows

    plan = tmp_path / "plan"
    plan.write_text("fail:settle_timeout")
    status_path = tmp_path / "farmer_status.json"
    monkeypatch.setenv("FAKE_GAME_PROFILE", str(tmp_path))
    monkeypatch.setenv("FAKE_SUPERVISED_PLAN", str(plan))
    monkeypatch.setenv("FARMER_SESSION_ID", "afk-test")
    monkeypatch.setattr(os, "_exit", sys.exit)
    original = windows._MoveFileExW
    injected = False

    def move(src, dst, flags):
        nonlocal injected
        if Path(dst) == status_path and json.loads(Path(src).read_bytes())["terminal"] and not injected:
            injected = True
            ctypes.set_last_error(windows.ERROR_SHARING_VIOLATION)
            return 0
        return original(src, dst, flags)

    monkeypatch.setattr(windows, "_MoveFileExW", move)
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(FAKE))
    assert injected and exc.value.code == 1
    terminal = json.loads(status_path.read_bytes())
    assert terminal["terminal"] is True
    assert terminal["finish_reason"] == "settle_timeout"


@pytest.mark.parametrize(("fault", "next_phase", "reason"), [
    (PermissionError, "paused", None),
    (FileNotFoundError, "paused", None),
    (FileNotFoundError, "done", None),
    (PermissionError, "failed", None),
    (FileNotFoundError, "run", "heartbeat_stale"),
])
def test_stale_verdict_is_checked_against_current_status_and_exit(tmp_path, monkeypatch,
                                                               fault, next_phase, reason):
    session = "afk-" + uuid.uuid4().hex
    status_path = tmp_path / "farmer_status.json"
    os_ = platform.current()
    monkeypatch.setattr(os_, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(os_, "game_running", lambda: False)
    monkeypatch.setattr(os_, "check_network_isolation", lambda: "")
    monkeypatch.setenv("FARMER_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(launch, "check_prerequisites", lambda *_: (tmp_path / "game", None))
    monkeypatch.setattr(launch, "preflight", lambda *_, **__: SimpleNamespace(argv=[tmp_path / "game"], config=None))
    reads = polls = 0
    killed = False
    monkeypatch.setattr(supervisor, "time", SimpleNamespace(monotonic=lambda: float(polls * 2), time=time.time))

    class Tree(platform.ProcessTree):
        def wait(self, timeout=None):
            nonlocal polls
            if killed:
                return 9
            # Failed exited during the timed-out poll's status read; paused/done
            # are still alive until the next ordinary poll.
            if (next_phase == "failed" and reads >= 2) or (next_phase != "run" and polls >= 3):
                return int(next_phase == "failed")
            if timeout:
                polls += 1
                if polls == 3 and next_phase in ("paused", "done"):
                    return 0
            raise subprocess.TimeoutExpired("fake game", timeout)

        def kill(self):
            nonlocal killed
            killed = True

    def read(path, *, retry_missing=False):
        nonlocal reads
        if path != status_path:
            return path.read_bytes()
        reads += 1
        rename_gap = fault is FileNotFoundError and not retry_missing
        if reads == 2 or (reads == 3 and (next_phase in ("failed", "run") or rename_gap)):
            raise fault(path)
        if reads == 4 and next_phase == "done":
            raise PermissionError(path)  # The explicit terminal status was already observed in poll 2.
        phase = "run" if reads == 1 else "done" if polls >= 3 else next_phase
        return json.dumps({"session": session, "phase": phase, "heartbeat_seq": 1 if phase == "run" else reads,
                           "terminal": phase in ("done", "failed"), "failed": phase == "failed",
                           "finish_reason": "settle_timeout" if phase == "failed" else ""}).encode()

    monkeypatch.setattr(os_, "spawn_tree", lambda *_, **__: Tree())
    monkeypatch.setattr(os_, "read_shared", read)
    watcher = supervisor.Supervisor(os_, tmp_path, supervisor.Policy(heartbeat_interval=0.5),
                                    lambda: None, lambda *_: None, state=SimpleNamespace(observe_farmer=lambda *_, **__: None))
    result = launch.run_attempt(os_, tmp_path, None, session, watch=watcher._watcher())
    assert result.forced_reason == reason
    if next_phase == "failed":
        assert result.code == 1
        assert result.status["finish_reason"] == "settle_timeout"
    elif reason is None:
        assert result.clean(os_)


@pytest.mark.parametrize("before_kill", ["settle", "exit", "advanced", "missing"])
def test_run_stall_is_rechecked_before_killing(tmp_path, monkeypatch, before_kill):
    session = "afk-" + uuid.uuid4().hex
    status_path = tmp_path / "farmer_status.json"
    os_ = platform.current()
    monkeypatch.setattr(os_, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(os_, "game_running", lambda: False)
    monkeypatch.setattr(os_, "check_network_isolation", lambda: "")
    monkeypatch.setenv("FARMER_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(launch, "check_prerequisites", lambda *_: (tmp_path / "game", None))
    monkeypatch.setattr(launch, "preflight", lambda *_, **__: SimpleNamespace(argv=[tmp_path / "game"], config=None))
    reads = polls = 0
    finished = killed = False
    monkeypatch.setattr(supervisor, "time", SimpleNamespace(monotonic=lambda: float(polls), time=time.time))

    class Tree(platform.ProcessTree):
        def wait(self, timeout=None):
            nonlocal polls, finished
            if killed:
                return 9
            if (timeout == 0 and before_kill == "exit") or (timeout and polls >= 2 and reads >= 3):
                finished = True
                return 0
            if timeout:
                polls += 1
            raise subprocess.TimeoutExpired("fake game", timeout)

        def kill(self):
            nonlocal killed
            killed = not finished

    def read(path, *, retry_missing=False):
        nonlocal reads
        if path != status_path:
            return path.read_bytes()
        reads += 1
        if before_kill == "missing" and reads == 3:
            assert retry_missing
            raise FileNotFoundError(path)
        phase = "done" if finished else "settle" if before_kill == "settle" and reads == 3 else "run"
        game_time = 641 if before_kill == "advanced" and reads >= 3 else 640
        return json.dumps({"session": session, "phase": phase, "heartbeat_seq": reads,
                           "game": {"time": game_time}, "terminal": finished}).encode()

    monkeypatch.setattr(os_, "spawn_tree", lambda *_, **__: Tree())
    monkeypatch.setattr(os_, "read_shared", read)
    watcher = supervisor.Supervisor(os_, tmp_path, supervisor.Policy(run_stall_window=1.0),
                                    lambda: None, lambda *_: None, state=SimpleNamespace(observe_farmer=lambda *_, **__: None))
    result = launch.run_attempt(os_, tmp_path, None, session, watch=watcher._watcher())
    assert polls == 2  # The third read happened before the next regular poll.
    assert not killed
    assert result.clean(os_)


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


def test_frozen_run_with_fresh_heartbeat_restarts_and_records_stall(farm):
    plan_game(farm, "commands:timed-stall", "clean:max_runs")
    with farm.service(run_stall_window=0.6, heartbeat_interval=4.0):
        farm.start()
        state = wait_for(lambda: read_state(farm.os_), lambda saved: bool(saved.run_progress))
        assert state.run_progress["game_time"] == 640
        assert state.run_progress["window"] == 0.6
        assert state.run_progress["in_raid"] is False
        assert state.heartbeat_stale_after == 12.0
        assert state.run_progress["at_monotonic"] <= time.monotonic()
        outcome, directory = farm.outcome()
        rows = wait_for(lambda: read_history(farm.os_))

    assert (outcome["kind"], outcome["reason"]) == ("finished", "max_runs")
    assert [(attempt["outcome"], attempt["reason"]) for attempt in outcome["attempts"]] == [
        ("failed", "run_stalled"), ("finished", "max_runs"),
    ]
    saved = json.loads((directory / "attempt-01.status.json").read_bytes())
    assert saved["phase"] == "run" and saved["game"]["time"] == 640
    assert saved["heartbeat_seq"] > 5
    assert saved["session"] == farm.status("done")["session"] == outcome["session"]
    assert rows[0]["reason"] == "max_runs"
    assert rows[0]["attempt_failures"] == ["run_stalled"]


@pytest.mark.parametrize(("mode", "phase"), [
    ("phase-settle", "settle"), ("phase-keep", "keep"), ("phase-maint", "maint"),
    ("phase-idle", "idle"), ("endless", "run"), ("clock-reset", "run"), ("raid", "run"),
])
def test_other_phases_progress_and_short_raids_do_not_trigger_run_stall(farm, mode, phase):
    plan_game(farm, f"commands:{mode}")
    with farm.service(run_stall_window=0.45, raid_stall_window=10):
        farm.start()
        initial = farm.status(phase)
        wait_for(lambda: json.loads(farm.os_.read_shared(farm.status_path)), lambda d: (
            d["phase"] == phase and d["heartbeat"] - initial["heartbeat"] >= 0.7
        ))
        farm.send("finish")
        outcome, _ = farm.outcome()
    assert [(attempt["outcome"], attempt["reason"]) for attempt in outcome["attempts"]] == [
        ("finished", "finish"),
    ]


def test_frozen_raid_restarts_after_the_raid_window(farm):
    plan_game(farm, "commands:raid", "clean:max_runs")
    with farm.service(run_stall_window=0.2, raid_stall_window=0.8):
        farm.start()
        outcome, directory = farm.outcome()
    failed, finished = outcome["attempts"]
    assert (failed["outcome"], failed["reason"]) == ("failed", "run_stalled")
    assert "in a raid" in failed["detail"] and "0.8 s" in failed["detail"]
    saved = json.loads((directory / "attempt-01.status.json").read_bytes())
    assert saved["game"]["in_raid"] is True
    assert saved["heartbeat_seq"] >= 12  # The shorter normal window would kill sooner.
    assert finished["outcome"] == "finished"


def test_repeated_run_stalls_quarantine(farm):
    plan_game(farm, "commands")
    with farm.service(run_stall_window=0.55):
        farm.start()
        outcome, directory = farm.outcome()
        state = wait_for(lambda: read_state(farm.os_), lambda saved: bool(saved.quarantine))
    assert outcome["kind"] == "quarantined"
    assert [attempt["reason"] for attempt in outcome["attempts"]] == ["run_stalled"] * 3
    assert farm.notifications() == ["fail", "fail", "quarantine"]
    report = json.loads((directory / "quarantine.json").read_bytes())
    assert report["last_failure"] == "run_stalled"
    assert "Run stalled" in state.quarantine["detail"]
    assert read_history(farm.os_)[0]["attempt_failures"] == ["run_stalled"]


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
    # A long startup grace keeps "stale heartbeat" (3 x 0.5 s) clearly apart from
    # "no heartbeat yet"; time the outcome itself, not the fixture's shutdown.
    with farm.service(startup_grace=10.0):
        started = time.monotonic()
        farm.start()
        grandchild = int(wait_for(lambda: farm.plan.with_suffix(".grandchild").read_text()))
        outcome, _ = farm.outcome()
        elapsed = time.monotonic() - started
    assert outcome["attempts"][0]["reason"] == "heartbeat_stale"
    assert outcome["kind"] == "finished"
    assert elapsed < 6  # the stale window, not the 10 s startup grace
    wait_for(lambda: not _alive(grandchild))
    assert farm.notifications() == ["fail", "stop"]


@POSIX
def test_sigstopped_farmer_is_a_stale_heartbeat_and_restarts(farm):
    plan_game(farm, "commands", "clean:stop")
    with farm.service():
        farm.start()
        running = farm.status("run")["pid"]
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


@POSIX
@pytest.mark.parametrize(("show_game_window", "step", "finished"), [
    (True, "done-sigabrt", True),
    (False, "done-sigabrt", False),
    (True, "run-sigabrt", False),
    (True, "exit:134", False),
])
def test_only_a_windowed_abort_after_verified_finish_is_a_terminal_outcome(farm, show_game_window, step, finished):
    plan_game(farm, f"{step}:goal" if ":" not in step else step, "clean:stop")
    with farm.service():
        commands.submit(farm.os_, commands.Start(None, farm.preset, commands.SessionSettings(
            show_game_window=show_game_window,
        )))
        outcome, _ = farm.outcome()
    assert outcome["kind"] == "finished"
    if finished:
        assert outcome["reason"] == "goal"
        assert len(outcome["attempts"]) == 1
        assert outcome["attempts"][0]["exit_code"] == -signal.SIGABRT
    else:
        assert outcome["reason"] == "stop"
        assert len(outcome["attempts"]) == 2
        assert outcome["attempts"][0]["outcome"] == "failed"


@pytest.mark.parametrize("legacy_lock", [False, True])
def test_second_supervisor_leaves_the_running_session_alone(farm, legacy_lock):
    session = farm.data / "session.json"
    session.write_text("afk-first")
    lock_path = farm.profile / "farmer_supervisor.lock" if legacy_lock else farm.data / "service.lock"
    with farm.os_.acquire_lock(lock_path):
        second = subprocess.run(SERVICE, capture_output=True,
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
        result = subprocess.run(SERVICE, capture_output=True,
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
        check = commands.submit(farm.os_, "check_again")
        wait_for(lambda: not check.exists())
        assert read_state(farm.os_).quarantine == state.quarantine
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
        grandchild = int(wait_for(lambda: farm.plan.with_suffix(".grandchild").read_text()))
        started = time.monotonic()
        proc.send_signal(signal.SIGTERM)
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
        proc.send_signal(signal.SIGTERM)
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
    (farm.profile / "patches/patch_official.pck").write_bytes(b"changed without state update")
    fake_bin = tmp_path / "notification-bin"
    fake_bin.mkdir()
    fake_notify = fake_bin / "notify-send"
    fake_notify.write_text("#!/bin/sh\nexit 0\n")
    fake_notify.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    with subprocess.Popen(command, stdout=subprocess.DEVNULL, env=env) as proc:
        try:
            farm.start()
            outcome, _ = farm.outcome()
            assert outcome["reason"] == "preflight_failed"
        finally:
            proc.send_signal(signal.SIGTERM)
            assert proc.wait(timeout=5) == 0


def test_crash_recovery_reuses_session_without_replaying_the_start(farm):
    (farm.profile / "patches/patch_official.pck").write_bytes(b"changed without state update")
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
        settled = wait_for(lambda: read_state(farm.os_),
                           lambda state: state.last_outcome and state.last_outcome["reason"] == "goal")
        assert settled.command_refusals == ()
    refusal = json.loads(commands.rejection_path(farm.os_, duplicate).read_bytes())
    assert refusal == {"command": "start", "reason": "AFK session already active"}
    assert not (farm.data / "command-rejections" / next_start.name).exists()
    by_reason = {outcome["reason"]: outcome for outcome in outcomes}
    assert by_reason["finish"]["session"] == current
    assert by_reason["goal"]["session"] != current
    assert all(outcome["kind"] == "finished" and len(outcome["attempts"]) == 1 for outcome in outcomes)
    with farm.service():
        idle = wait_for(lambda: read_state(farm.os_), lambda state: state.kind is StateKind.IDLE)
        assert idle.command_refusals == ()


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


@pytest.mark.parametrize(("broken", "payload"), [
    ("outcome.json", None),
    ("outcome.json", b"{broken"),
    ("outcome.json", b"{}"),
    ("quarantine.json", None),
    ("quarantine.json", b"{broken"),
    ("quarantine.json", b"{}"),
])
def test_corrupt_terminal_records_are_startup_quarantined(farm, broken, payload):
    plan_game(farm, "clean:goal")
    session_id = "afk-" + uuid.uuid4().hex
    request = farm.start()
    marker = farm.data / "session.json"
    marker.write_text(json.dumps({
        "id": session_id, "start": json.loads(request.read_bytes()),
        "request": request.name, "profile": str(farm.profile),
    }))
    directory = farm.data / "logs" / f"supervisor-{session_id}"
    directory.mkdir(parents=True)
    for name, record in {
        "outcome.json": {"session": session_id, "kind": "quarantined", "reason": "preflight_failed", "attempts": []},
        "quarantine.json": {"reason": "preflight_failed", "detail": "Missing game", "attempts": []},
    }.items():
        if name != broken:
            (directory / name).write_text(json.dumps(record))
        elif payload is not None:
            (directory / name).write_bytes(payload)

    with farm.service() as proc:
        wait_for(lambda: not marker.exists() or proc.poll() is not None or farm.plan.with_suffix(".count").exists())
        assert proc.poll() is None
        report = read_state(farm.os_).quarantine
        assert report is not None and report["reason"] == "invalid_saved_session"
        assert str(directory / broken) in report["detail"]
        assert (farm.data / report["diagnostics"] / "session.json").is_file()
        assert read_history(farm.os_) == []
        assert not farm.plan.with_suffix(".count").exists()

        farm.start()
        next_outcome = wait_for(lambda: read_state(farm.os_).last_outcome)
        assert next_outcome["kind"] == "finished" and next_outcome["session"] != session_id


@pytest.mark.parametrize("recovering", [False, True])
def test_unwritable_history_does_not_prevent_terminal_state_or_later_sessions(farm, recovering):
    plan_game(farm, "clean:goal")
    path = history_path(farm.os_)
    path.mkdir()  # A directory at the history path fails reads and writes on both platforms.
    if recovering:
        session_id = "afk-" + uuid.uuid4().hex
        request = farm.start()
        (farm.data / "session.json").write_text(json.dumps({
            "id": session_id, "start": json.loads(request.read_bytes()),
            "request": request.name, "profile": str(farm.profile),
        }))
        directory = farm.data / "logs" / f"supervisor-{session_id}"
        directory.mkdir(parents=True)
        (directory / "outcome.json").write_text(json.dumps({
            "session": session_id, "kind": "finished", "reason": "goal", "attempts": [], "totals": {},
        }))

    with farm.service() as proc:
        if not recovering:
            farm.start()
        wait_for(lambda: read_state(farm.os_).last_outcome or proc.poll() is not None)
        assert proc.poll() is None
        terminal = read_state(farm.os_)
        assert terminal.kind is StateKind.IDLE
        assert terminal.session_id is None and terminal.last_outcome["kind"] == "finished"
        assert farm.outcome()[0] == terminal.last_outcome
        wait_for(farm.notifications, lambda events: "history_failed" in events)
        wait_for(lambda: not (farm.data / "session.json").exists())

        path.rmdir()
        farm.start()
        row, = wait_for(lambda: read_history(farm.os_))
        assert row["outcome"] == "finished" and row["session_id"] != terminal.last_outcome["session"]
