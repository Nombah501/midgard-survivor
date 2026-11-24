"""The service entry point, run as a process against a temporary user dir."""

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from midgard_farm import platform
from midgard_farm.core.commands import Character, Start, submit
from midgard_farm.core.state import StateKind, read_state

from test_profile import godot_root, make_profile


SERVICE = [sys.executable, str(Path(__file__).with_name("fake_notification_service.py"))]


def service_env(home):
    return dict(os.environ, XDG_DATA_HOME=str(home), APPDATA=str(home), LOCALAPPDATA=str(home))


def run_service(home):
    return subprocess.run(SERVICE, env=service_env(home), capture_output=True, encoding="utf-8", timeout=5)


def test_service_reports_the_profile_it_found(tmp_path):
    profile = make_profile(godot_root(tmp_path), "Мидгард Survivors")

    output = tmp_path / "service.log"
    with output.open("wb") as log, subprocess.Popen(SERVICE, env=service_env(tmp_path), stdout=log) as service:
        try:
            deadline = time.monotonic() + 5
            while str(profile) not in output.read_text(encoding="utf-8"):
                assert service.poll() is None and time.monotonic() < deadline
                time.sleep(0.01)
            assert service.poll() is None  # The service remains available for Start.
        finally:
            service.terminate()
            service.wait(timeout=5)


def test_service_waits_for_a_missing_profile_and_discovers_it(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    output = tmp_path / "service.log"
    with output.open("wb") as log, subprocess.Popen(SERVICE, env=service_env(tmp_path), stdout=log) as service:
        def wait_for(message):
            deadline = time.monotonic() + 5
            while message not in output.read_text(encoding="utf-8"):
                assert service.poll() is None and time.monotonic() < deadline
                time.sleep(0.01)

        try:
            wait_for("profile not found")
            unavailable = read_state(os_)
            assert unavailable.kind is StateKind.FARMER_UNAVAILABLE
            assert unavailable.reason == "start the game and accept the update"
            request = submit(os_, Start(Character("archer", 1)))
            wait_for("refused start")
            refusal, = read_state(os_).command_refusals
            assert refusal["request"] == request.name and refusal["reason"] == unavailable.reason
            assert service.poll() is None
            profile = make_profile(godot_root(tmp_path), "Late Midgard Survivors")
            wait_for(str(profile))
            assert service.poll() is None
        finally:
            if service.poll() is None:
                service.terminate()
            service.wait(timeout=5)


def test_missing_profile_is_still_unfixable_for_standalone_launch(tmp_path):
    result = subprocess.run([*SERVICE, "launch"], env=service_env(tmp_path),
                            capture_output=True, encoding="utf-8", timeout=5)
    assert result.returncode == 78
    assert "launch the game once" in result.stderr


def test_second_service_instance_is_refused(tmp_path, monkeypatch):
    make_profile(godot_root(tmp_path), "Midgard Survivors")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    os_.app_data_dir().mkdir(parents=True)

    with os_.acquire_lock(os_.app_data_dir() / "service.lock"):
        result = run_service(tmp_path)

    assert result.returncode == 75
    assert "already running" in result.stderr


def test_unusable_app_data_quarantines_instead_of_crashing(tmp_path):
    home = tmp_path / "not-a-directory"
    home.touch()

    result = run_service(home)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "notify quarantine: app data directory unusable" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("foreign", [False, True])
def test_corrupt_or_foreign_saved_session_is_quarantined(tmp_path, monkeypatch, foreign):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    data = platform.current().app_data_dir()
    profile = make_profile(godot_root(tmp_path), "Midgard Survivors")
    data.mkdir(parents=True)
    marker = data / "session.json"
    saved = json.dumps({
        "id": "afk-" + uuid.uuid4().hex,
        "request": "consumed-request.json",
        "profile": str(profile.with_name("Different profile")),
        "start": Start(Character("thief", 0)).payload(),
    }) if foreign else "{corrupt"
    marker.write_text(saved)
    output = tmp_path / "quarantine.log"
    with output.open("wb") as log, subprocess.Popen(SERVICE, env=service_env(tmp_path), stdout=log) as service:
        try:
            deadline = time.monotonic() + 5
            while marker.exists():
                assert service.poll() is None and time.monotonic() < deadline
                time.sleep(0.01)
            assert service.poll() is None
            record = json.loads(platform.current().read_shared(data / "quarantine.json"))
            assert record["reason"] == "invalid_saved_session"
            assert record["detail"]
            diagnostics = data / record["diagnostics"]
            assert (diagnostics / "session.json").read_bytes() == saved.encode()
            assert json.loads((diagnostics / "quarantine.json").read_bytes()) == record
            assert "notify quarantine: saved AFK session unusable" in output.read_text(encoding="utf-8")
            assert not (profile / "farmer_stop").exists()
        finally:
            if service.poll() is None:
                service.terminate()
            service.wait(timeout=5)


def test_frozen_systemd_unit_executes_the_binary_directly(tmp_path):
    script = (
        "import sys\n"
        "from midgard_farm.service import main\n"
        "sys.frozen = True\n"
        "sys.executable = '/opt/Midgard Farm %local/$current/service'\n"
        "raise SystemExit(main())\n"
    )
    result = subprocess.run([sys.executable, "-c", script, "--print-unit"], env=service_env(tmp_path),
                            check=True, capture_output=True, encoding="utf-8", timeout=5)
    exec_start, = (line for line in result.stdout.splitlines() if line.startswith("ExecStart="))
    assert exec_start == 'ExecStart="/opt/Midgard Farm %%local/$$current/service"'
    assert "KillMode=mixed\n" in result.stdout
    assert "TimeoutStopSec=90\n" in result.stdout


def test_service_reports_both_ambiguous_profiles_in_state_and_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    make_profile(godot_root(tmp_path), "First game profile")
    make_profile(godot_root(tmp_path), "Second game profile")
    request = submit(os_, Start(Character("archer", 1)))
    with subprocess.Popen(SERVICE, env=service_env(tmp_path), stdout=subprocess.DEVNULL) as child:
        try:
            deadline = time.monotonic() + 5
            while not (state := read_state(os_)).command_refusals:
                assert child.poll() is None and time.monotonic() < deadline
                time.sleep(0.01)
            assert state.kind is StateKind.FARMER_UNAVAILABLE
            assert state.reason.startswith("several profiles under ")
            assert "First game profile, Second game profile" in state.reason
            assert state.command_refusals[0]["reason"] == state.reason
            assert state.command_refusals[0]["request"] == request.name
        finally:
            child.terminate()
            child.wait(timeout=5)


@pytest.mark.parametrize("frozen", [False, True])
@pytest.mark.skipif(sys.platform != "win32", reason="windowless task executable")
def test_print_task_uses_windowless_service_without_app_data(tmp_path, frozen):
    from xml.etree import ElementTree

    sibling = tmp_path / ("Frozen Midgard Farm.exe" if frozen else "pythonw.exe")
    sibling.touch()
    executable = sibling if frozen else sibling.with_name("python.exe")
    script = (
        "import subprocess, sys\n"
        "from midgard_farm.service import main\n"
        "def whoami(argv, **kwargs):\n"
        "    assert argv[0].lower().endswith('whoami.exe'), argv\n"
        "    return subprocess.CompletedProcess(argv, 0, stdout='\"PC\\\\user\",\"S-1-5-21-1-2-3-1001\"\\n')\n"
        "subprocess.run = whoami\n"
        f"sys.frozen = {frozen!r}\n"
        f"sys.executable = {str(executable)!r}\n"
        "raise SystemExit(main())\n"
    )
    result = subprocess.run([sys.executable, "-c", script, "--print-task"], env=service_env(tmp_path),
                            check=True, capture_output=True, encoding="utf-8", timeout=5)
    task = ElementTree.fromstring(result.stdout)
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert task.findtext("t:Actions/t:Exec/t:Command", namespaces=ns) == str(sibling)
    assert task.findtext("t:Actions/t:Exec/t:Arguments", namespaces=ns) == (
        None if frozen else "-m midgard_farm.service"
    )
    assert list(tmp_path.iterdir()) == [sibling]


def test_windowless_service_can_start_with_no_standard_streams(tmp_path):
    script = (
        "import sys\n"
        "from midgard_farm import service\n"
        "sys.stdout = sys.stderr = None\n"
        "def serve(*args):\n"
        "    print('windowless')\n"
        "    return 27\n"
        "service._serve = serve\n"
        "raise SystemExit(service.main())\n"
    )
    result = subprocess.run([sys.executable, "-c", script], env=service_env(tmp_path),
                            capture_output=True, timeout=5)
    assert result.returncode == 27, result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows game discovery before the profile exists")
def test_windows_service_learns_the_game_while_waiting_for_a_profile(tmp_path, monkeypatch, service_game_platform):
    from test_platform import fake_game

    monkeypatch.delenv("GAME_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_, _ = service_game_platform
    argv = fake_game(tmp_path)
    learned = os_.app_data_dir() / "game-executable.txt"
    script = (
        "import sys\n"
        "from midgard_farm import platform, service\n"
        "pid = int(sys.argv.pop(1))\n"
        "local_platform = platform.current()\n"
        "local_platform.game_pids = lambda: {pid}\n"
        "platform.current = lambda: local_platform\n"
        "raise SystemExit(service.main())\n"
    )
    with os_.spawn_tree(argv, stdout=subprocess.DEVNULL) as game:
        with subprocess.Popen([sys.executable, "-c", script, str(game.popen.pid)],
                              env=service_env(tmp_path), stdout=subprocess.DEVNULL) as service:
            try:
                deadline = time.monotonic() + 10
                while not learned.exists():
                    assert service.poll() is None
                    assert time.monotonic() < deadline, "the service did not learn the running game"
                    time.sleep(0.05)
            finally:
                service.terminate()
                service.wait(timeout=5)

    monkeypatch.setattr(os_, "game_pids", set)
    assert os_.game_executable() == Path(argv[0])


def test_restore_official_is_refused_explicitly_when_no_profile_exists(tmp_path, monkeypatch):
    from midgard_farm.core.commands import rejection_path

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    request = submit(os_, "restore_official")
    with subprocess.Popen(SERVICE, env=service_env(tmp_path), stdout=subprocess.DEVNULL) as child:
        try:
            deadline = time.monotonic() + 5
            while request.exists():
                assert child.poll() is None and time.monotonic() < deadline
                time.sleep(0.02)
            rejection = json.loads(os_.read_shared(rejection_path(os_, request)))
            assert rejection == {"command": "restore_official", "reason": "start the game and accept the update"}
        finally:
            child.terminate()
            child.wait(timeout=5)
