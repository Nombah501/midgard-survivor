import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

from midgard_farm.core import commands
from midgard_farm.platform import Platform, current


@dataclass
class FarmFiles:
    platform: Platform
    data: Path
    profile: Path

    def state(self, kind="idle", **fields):
        self.platform.write_atomic(self.data / "state.json", json.dumps({
            "v": 1, "kind": kind, "updated_at": time.time(), "refresh_interval": 10, **fields,
        }).encode())

    def status(self, **fields):
        self.platform.write_atomic(self.profile / "farmer_status.json", json.dumps(fields).encode())


@pytest.fixture
def farm(tmp_path, monkeypatch):
    for var in ("XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA", "GAME_DIR"):
        monkeypatch.setenv(var, str(tmp_path / var))

    def forbid_system_tool(*args, **kwargs):
        pytest.fail("GUI test tried to run a real system tool")

    monkeypatch.setattr(subprocess, "run", forbid_system_tool)
    platform = current()
    data = platform.app_data_dir()
    assert data.is_relative_to(tmp_path)
    data.mkdir(parents=True)
    profile = platform.godot_user_data_root() / "Fixture Profile"
    assert profile.is_relative_to(tmp_path)
    (profile / "patches").mkdir(parents=True)
    (profile / "patches" / "state.json").write_text("{}", encoding="utf-8")
    (profile / "profile.json").write_bytes(b"GDEC synthetic opaque profile")
    return FarmFiles(platform, data, profile)


def test_start_writes_only_a_request_and_remembers_both_picks(farm):
    from midgard_farm.gui.model import SessionModel

    farm.state()
    model = SessionModel(farm.platform)
    view = model.poll()
    assert view.phase == "Ready to start"
    assert view.can_start
    model.select_character(view.characters.index("Bard"))
    model.select_preset(view.presets.index("steady.json"))
    assert model.start()

    [request] = list(commands.directory(farm.platform).glob("*.json"))
    command = commands.decode(json.loads(request.read_bytes()))
    assert isinstance(command, commands.Start)
    assert command.character == commands.Character("archer", 1)
    assert command.preset.name == "steady.json"
    assert not model.poll().can_start
    assert model.start() is None  # Do not queue a second Start before the service responds.
    assert (farm.profile / "profile.json").read_bytes() == b"GDEC synthetic opaque profile"
    assert not (farm.profile / "farmer_command").exists()
    assert not (farm.data / "config.json").exists()

    view = SessionModel(farm.platform).poll()
    assert view.characters[view.character_index] == "Bard"
    assert view.presets[view.preset_index] == "steady.json"


def test_poll_displays_only_matching_run_and_uses_farmer_rates(farm, monkeypatch):
    from midgard_farm.gui.model import SessionModel

    monkeypatch.setattr(time, "time", lambda: 1000.0)

    farm.state("active", session_id="afk-fixture", farmer_phase="run", last_heartbeat=time.time() - 7.2)
    farm.status(session="older-afk", run_id="old-run", rates={"zeny_h": 777})
    (farm.data / "history.jsonl").write_text(
        '{"v":1,"timestamp":123,"kind":"session","session_id":"older-afk"}\n{"torn"', encoding="utf-8",
    )
    model = SessionModel(farm.platform)
    view = model.poll()
    assert view.phase == "Run in progress"
    assert view.heartbeat_age == "7 s ago"
    assert view.zeny == "—"
    assert view.current_run == "—"
    assert model.history[0]["session_id"] == "older-afk"

    active_status(farm)
    view = model.poll()
    assert view.zeny == "1,175,745"
    assert view.materials == "42.1 / 3.8"
    assert view.current_run == "Run 13 · Payon Forest · Difficulty 18"
    assert view.run_detail == "Level 116 · 08:42 · HP 78%"
    assert not view.can_start
    assert view.can_control


def active_status(farm):
    farm.status(session="afk-fixture", run_id="run-13", phase="run", terminal=False,
                totals={"started": 13, "runs": 12, "wins": 11, "lost": 0},
                rates={"zeny_h": 1175744.7, "ore_h": 42.1, "crumbs_h": 3.8, "kills_min": 220.4},
                target={"stage": "payon", "danger": 18},
                game={"running": True, "stage": "payon", "danger": 18, "level": 116,
                      "time": 522, "hp": 780, "max_hp": 1000})


def test_start_refusal_is_correlated_and_a_new_start_clears_it(farm):
    from midgard_farm.gui.model import SessionModel

    farm.state(command_refusals=[{"request": "unrelated.json", "command": "start", "reason": "Other Start"}])
    model = SessionModel(farm.platform)
    assert not model.poll().start_refusal
    request = model.start()
    assert request
    farm.state(command_refusals=[
        {"request": "unrelated.json", "command": "start", "reason": "Other Start"},
        {"request": request.name, "command": "start", "reason": "Game not found"},
    ])
    view = model.poll()
    assert view.start_refusal == "Game not found"
    assert view.can_start
    assert model.start()
    assert not model.poll().start_refusal


@pytest.mark.parametrize(("kind", "fields", "reason"), [
    ("idle", {"updated_at": 1}, "Service not running"),
    ("farmer_unavailable", {"reason": "Game not found"}, "Game not found"),
    ("idle", {"quarantine": {"reason": "build_failed", "detail": "Compiler failed"}}, "Compiler failed"),
    ("waiting_for_game", {"reason": "Waiting for the game to close"}, "Waiting for the game to close"),
])
def test_start_blockers_come_from_state(farm, kind, fields, reason):
    from midgard_farm.gui.model import SessionModel

    farm.state(kind, **fields)
    model = SessionModel(farm.platform)
    view = model.poll()
    assert reason in view.start_reason
    assert not view.can_start
    assert model.start() is None
    assert not commands.directory(farm.platform).exists()


def test_quarantine_uses_the_matching_session_diagnostic(farm):
    from midgard_farm.gui.model import SessionModel

    session = "afk-" + "1" * 32
    logs = farm.data / "logs" / f"supervisor-{session}"
    logs.mkdir(parents=True)
    (logs / "quarantine.json").write_text(
        '{"reason":"heartbeat_stale","detail":"No new heartbeat for 15 seconds"}', encoding="utf-8",
    )
    farm.state(quarantine={"reason": "heartbeat_stale"}, last_outcome={"kind": "quarantined", "session": session})
    view = SessionModel(farm.platform).poll()
    assert view.phase == "Quarantine"
    assert view.start_reason == "No new heartbeat for 15 seconds"
    assert not view.can_start


def test_fixed_preset_uses_its_character_without_losing_normal_pick(farm):
    from midgard_farm.gui.model import SessionModel

    farm.state()
    model = SessionModel(farm.platform)
    view = model.poll()
    model.select_character(view.characters.index("Bard"))
    model.select_preset(view.presets.index("sniper-hell.json"))
    view = model.poll()
    assert view.characters[view.character_index] == "Sniper"
    assert not view.can_pick_character
    assert "Rachel Sanctuary" in view.preset_description
    request = model.start()
    assert request
    command = commands.decode(json.loads(request.read_bytes()))
    assert isinstance(command, commands.Start)
    assert command.character == commands.Character("archer", 0)
    model.select_preset(view.presets.index("night.json"))
    view = model.poll()
    assert view.characters[view.character_index] == "Bard"


def test_service_start_uses_only_the_platform_service_tool(farm, monkeypatch):
    from midgard_farm.gui.model import SessionModel

    calls = []

    def run_tool(argv, **kwargs):
        calls.append(argv)
        raise subprocess.CalledProcessError(1, argv, stderr="Not registered")

    monkeypatch.setattr(subprocess, "run", run_tool)
    model = SessionModel(farm.platform)
    farm.state()
    assert not model.start_service()
    assert not calls
    farm.state(updated_at=1)
    assert model.poll().service_missing
    assert not model.start_service()
    expected = (["schtasks.exe", "/Run", "/TN", "Midgard Farm"] if farm.platform.release_os == "windows"
                else ["systemctl", "--user", "start", "midgard-farm.service"])
    assert calls == [expected]
    assert "Not registered" in model.poll().action_error
    assert not commands.directory(farm.platform).exists()


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    from PySide6.QtGui import QGuiApplication

    return QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture
def qt_warnings(qt_app):
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    messages = []

    def capture(level, context, message):
        if level in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            messages.append(message)

    previous = qInstallMessageHandler(capture)
    try:
        yield messages
    finally:
        qInstallMessageHandler(previous)


def qml_item(window, name):
    from PySide6.QtCore import QObject

    item = window.findChild(QObject, name)
    assert item is not None, name
    return item


def wait_until(predicate):
    from PySide6.QtTest import QTest

    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, "Timed out waiting for the Qt window to update"
        QTest.qWait(20)


@pytest.mark.parametrize(("screen", "phase", "extra"), [
    ("idle", "Ready to start", ("startButton", "enabled", True)),
    ("active-with-income", "Run in progress", ("zenyValue", "text", "1,175,745")),
    ("refused-start", "Ready to start", ("startRefusal", "text", "Start refused: Game not found")),
    ("service-not-running", "Service not running", ("startServiceButton", "visible", True)),
    ("restarting", "Restarting in 15.0s", ("finishButton", "enabled", True)),
])
def test_afk_screen_renders(qt_app, qt_warnings, farm, tmp_path, screen, phase, extra):
    from PySide6.QtTest import QTest

    from midgard_farm.gui.model import SessionModel
    from midgard_farm.gui.window import load_window

    if screen == "active-with-income":
        farm.state("active", session_id="afk-fixture", farmer_phase="run", last_heartbeat=time.time() - 4)
        active_status(farm)
    elif screen == "service-not-running":
        farm.state(updated_at=1)
    elif screen == "restarting":
        farm.state("active", session_id="afk-" + "1" * 32, reason=phase)
    else:
        farm.state()
    model = SessionModel(farm.platform)
    if screen == "refused-start":
        request = model.start()
        assert request
        farm.state(command_refusals=[{"request": request.name, "command": "start", "reason": "Game not found"}])

    engine = load_window(model)
    try:
        [window] = engine.rootObjects()
        wait_until(lambda: qml_item(window, "phaseValue").property("text") == phase)
        QTest.qWait(50)
        item, prop, value = extra
        assert qml_item(window, item).property(prop) == value
        if screen == "restarting":
            assert qml_item(window, "sessionValue").property("text") == "afk-" + "1" * 32
            assert not qml_item(window, "pauseButton").property("enabled")
            assert qml_item(window, "abortButton").property("enabled")
        image = window.grabWindow()
        assert not image.isNull()
        assert image.save(str(tmp_path / f"{screen}.png"))
        window.close()
    finally:
        del engine
        qt_app.processEvents()
    assert not qt_warnings


def test_afk_buttons_and_window_close(qt_app, qt_warnings, farm):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from midgard_farm.gui.model import SessionModel
    from midgard_farm.gui.window import load_window

    def click(window, name):
        # A published snapshot can change visibility before Qt polishes the layout.
        assert not window.grabWindow().isNull()
        item = qml_item(window, name)
        assert item.property("visible") and item.property("enabled")
        local = item.boundingRect().center()
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=item.mapToScene(local).toPoint())
        qt_app.processEvents()

    def requests():
        return [json.loads(p.read_text(encoding="utf-8"))["command"]
                for p in sorted(commands.directory(farm.platform).glob("*.json"))]

    farm.state()
    engine = load_window(SessionModel(farm.platform))
    try:
        [window] = engine.rootObjects()
        assert QTest.qWaitForWindowExposed(window)
        dialog = qml_item(window, "abortDialog")
        wait_until(lambda: qml_item(window, "startButton").property("enabled"))
        click(window, "startButton")
        wait_until(lambda: requests() == ["start"])
        assert not dialog.property("visible")

        active_status(farm)
        farm.state("active", session_id="afk-fixture", farmer_phase="run")
        wait_until(lambda: qml_item(window, "phaseValue").property("text") == "Run in progress")
        click(window, "pauseButton")
        wait_until(lambda: requests() == ["start", "pause"])
        assert not dialog.property("visible")

        farm.state("active", session_id="afk-fixture", farmer_phase="paused")
        farm.status(session="afk-fixture", phase="paused")
        wait_until(lambda: qml_item(window, "pauseButton").property("text") == "Resume")
        click(window, "pauseButton")
        click(window, "finishButton")
        wait_until(lambda: requests() == ["start", "pause", "resume", "finish"])
        assert not dialog.property("visible")

        click(window, "abortButton")
        assert dialog.property("visible")
        assert "The current run settles; keep is skipped." in qml_item(window, "abortLoss").property("text")
        assert requests() == ["start", "pause", "resume", "finish"]
        click(window, "cancelAbort")
        assert requests() == ["start", "pause", "resume", "finish"]
        click(window, "abortButton")
        click(window, "confirmAbort")
        wait_until(lambda: requests() == ["start", "pause", "resume", "finish", "abort"])
        window.close()
        qt_app.processEvents()
        assert requests() == ["start", "pause", "resume", "finish", "abort"]
        assert not (farm.profile / "farmer_command").exists()
    finally:
        del engine
        qt_app.processEvents()
    assert not qt_warnings


@pytest.mark.parametrize("reason", ["AFK session in progress", "Restarting in 15.0s"])
def test_stop_commands_work_before_farmer_heartbeat(farm, reason):
    from midgard_farm.gui.model import SessionModel

    session = "afk-" + "1" * 32
    farm.state("active", session_id=session, reason=reason)
    model = SessionModel(farm.platform)
    assert model.poll().can_control
    assert model.control("pause", session_id=session) is None
    assert model.control("resume", session_id=session) is None
    assert model.control("finish", session_id=session)
    assert model.control("abort", session_id=session)
    requests = sorted(commands.directory(farm.platform).glob("*.json"))
    assert [json.loads(path.read_bytes())["command"] for path in requests] == ["finish", "abort"]


def test_slow_shared_read_keeps_published_state_and_qt_responsive(qt_app, qt_warnings, farm, monkeypatch):
    from PySide6.QtCore import QTimer

    from midgard_farm.gui.model import SessionModel
    from midgard_farm.gui.window import load_window

    reading = Event()
    release = Event()
    returned = Event()
    original = farm.platform.read_shared
    state_path = farm.data / "state.json"

    def slow_read(path, **kwargs):
        if path == state_path and not reading.is_set():
            reading.set()
            release.wait(timeout=4)
            returned.set()
        return original(path, **kwargs)

    farm.state()
    engine = load_window(SessionModel(farm.platform))
    try:
        [window] = engine.rootObjects()
        phase = qml_item(window, "phaseValue")
        wait_until(lambda: phase.property("text") == "Ready to start")
        farm.state("active", session_id="afk-fixture", reason="Restarting in 15.0s")
        monkeypatch.setattr(farm.platform, "read_shared", slow_read)
        wait_until(reading.is_set)

        gui_ticked = Event()
        QTimer.singleShot(0, gui_ticked.set)
        wait_until(gui_ticked.is_set)
        assert not returned.is_set()
        assert phase.property("text") == "Ready to start"

        release.set()
        wait_until(lambda: phase.property("text") == "Restarting in 15.0s")
        window.close()
    finally:
        release.set()
        del engine
        qt_app.processEvents()
    assert not qt_warnings
