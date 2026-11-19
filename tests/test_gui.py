import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

from midgard_farm.core import commands
from midgard_farm.core.history import append_event, history_path
from midgard_farm.core.supervisor import session_log_dir
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
    assert view.history.rows[0].session_id == "older-afk"

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
    logs = session_log_dir(farm.platform, session)
    logs.mkdir(parents=True)
    (logs / "quarantine.json").write_text(
        '{"reason":"heartbeat_stale","detail":"No new heartbeat for 15 seconds\\nMore detail",'
        '"attempts":[{"number":1,"outcome":"failed","reason":"heartbeat_stale"}]}', encoding="utf-8",
    )
    (logs / "attempt-01.log").touch()
    (logs / "attempt-01.status.json").touch()
    farm.state(quarantine={"reason": "heartbeat_stale", "diagnostics": logs.relative_to(farm.data).as_posix()},
               last_outcome={"kind": "quarantined", "session": session})
    view = SessionModel(farm.platform).poll()
    assert view.phase == "Quarantine"
    assert view.quarantine.detail == "No new heartbeat for 15 seconds"
    assert view.quarantine.action == "Start a new session"
    assert view.quarantine.attempts == ["Attempt 1 · Failed · heartbeat_stale"]
    assert set(map(Path, view.quarantine.paths)) == {
        logs / "quarantine.json", logs / "attempt-01.log", logs / "attempt-01.status.json",
    }
    assert view.can_start  # A new session is explicit; the service won't retry the quarantined one.


def test_idle_rebuild_quarantine_does_not_reuse_an_older_sessions_record(farm):
    from midgard_farm.gui.model import SessionModel

    session = "afk-" + 32 * "3"
    logs = session_log_dir(farm.platform, session)
    logs.mkdir(parents=True)
    (logs / "quarantine.json").write_text(
        '{"reason":"smoke_failed","detail":"Previous session failed"}', encoding="utf-8",
    )
    log = str(farm.data / "latest-smoke.log")
    farm.state("farmer_unavailable", quarantine={"reason": "smoke_failed", "detail": "Check again failed",
                                                "log_path": log},
               last_outcome={"kind": "quarantined", "session": session})
    view = SessionModel(farm.platform).poll()
    assert view.quarantine.detail == "Check again failed"
    assert view.quarantine.paths == [log]


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
    if farm.platform.release_os == "windows":
        tool = Path(os.environ["SystemRoot"]) / "System32" / "schtasks.exe"
        expected = [str(tool), "/Run", "/TN", "Midgard Farm"]
    else:
        expected = ["systemctl", "--user", "start", "midgard-farm.service"]
    assert calls == [expected]
    assert "Not registered" in model.poll().action_error
    assert not commands.directory(farm.platform).exists()


def test_preset_decides_is_sent_as_null_and_remembered(farm):
    from midgard_farm.gui.model import SessionModel

    farm.state()
    model = SessionModel(farm.platform)
    model.select_character(model.poll().characters.index("Preset decides"))
    request = model.start()
    assert request
    result = commands.decode(json.loads(request.read_bytes()))
    assert isinstance(result, commands.Start) and result.character is None
    view = SessionModel(farm.platform).poll()
    assert view.characters[view.character_index] == "Preset decides"


def history_fixture(farm):
    append_event(farm.platform, "session", timestamp=1_704_067_500, session_id="previous-night",
                 outcome="stopped", reason="abort", totals={"runs": 3, "wins": 2, "zeny": 6000})
    append_event(farm.platform, "app_update", timestamp=1_704_067_620, outcome="rolled_back", future={"foo": 1})
    append_event(farm.platform, "game_update", timestamp=1_704_067_560,
                 classification="game_update", outcome="ready")
    append_event(farm.platform, "session", timestamp=1_704_067_680, session_id="last-night",
                 outcome="finished", reason="max_minutes",
                 totals={"runs": 12, "wins": 10, "lost": 1, "wall_s": 1800, "zeny": 7200, "xp": 560,
                         "kills": 40, "coins": 3, "ymir": 2, "cards_gain": 4, "materials": {"ore": 4, "star_crumb": 2},
                         "future": ["skip"]})
    append_event(farm.platform, "future", timestamp=1_704_067_740, future=True)
    with history_path(farm.platform).open("ab") as file:
        file.write(b'{"v":1,"kind":"game_update"')


def test_history_is_interleaved_in_timestamp_order_with_last_night_detailed(farm):
    from midgard_farm.gui.model import SessionModel

    farm.state()
    history_fixture(farm)
    history = SessionModel(farm.platform).poll().history
    assert [row.title for row in history.rows] == [
        "AFK session · Finished", "App update · Rolled back", "Game update · Handled", "AFK session · Stopped",
    ]
    last_night, _, _, previous = history.rows
    assert "12 runs · 10 wins · 7,200 zeny" in last_night.summary
    assert "3 runs · 2 wins · 6,000 zeny" in previous.summary
    assert last_night.session_id == "last-night"
    assert dict((metric.label, metric.value) for metric in history.totals) == {
        "Runs": "12", "Wins": "10", "Lost": "1", "Time in runs": "0.5 h",
        "Zeny": "7,200", "XP": "560", "Kills": "40", "Cards": "4", "Coins": "3", "Ymir": "2",
    }
    assert history.rewards == "14,400 zeny · 1,120 XP · 6 coins · 4 Ymir · 8 cards"
    assert history.materials == "Ore 4 · Star Crumb 2"


@pytest.mark.parametrize(("classification", "kind", "state_title", "activity", "opens_game"), [
    ("current", "idle", "Current", "", False),
    ("game_update", "idle", "Game update", "", False),
    ("farmer_removed_or_stale", "idle", "Farmer patch removed or stale", "", False),
    ("game_reinstall", "farmer_unavailable", "Game reinstall", "", True),
    ("game_update", "waiting_for_game", "Game update", "Waiting for the game to close", False),
    ("game_update", "rebuilding", "Game update", "Rebuilding", False),
])
def test_updates_describes_the_classification_and_activity(farm, classification, kind, state_title,
                                                         activity, opens_game):
    from importlib.metadata import version

    from midgard_farm.gui.model import SessionModel

    farm.state(kind, game_update_classification=classification)
    updates = SessionModel(farm.platform).poll().updates
    assert (updates.game_state, updates.activity) == (state_title, activity)
    assert ("Open the game" in updates.game_detail) == opens_game
    assert ("start the game and accept the update" in updates.game_detail) == opens_game
    assert updates.app_version == version("midgard-farm")


def test_updates_shows_package_version_in_an_uninstalled_checkout(farm, monkeypatch):
    from importlib.metadata import PackageNotFoundError, version

    from midgard_farm import assets
    from midgard_farm.gui import model

    def unavailable(package):
        raise PackageNotFoundError(package)

    monkeypatch.setattr(assets, "distribution_version", unavailable)
    assert model.SessionModel(farm.platform).poll().updates.app_version == version("midgard-farm")


@pytest.mark.parametrize(("outcome", "reason", "label"), [
    ("ready", "", "Handled"),
    ("quarantine", "build_failed", "Build failed"),
    ("quarantine", "anchors_broken", "Anchors broke"),
    ("quarantine", "smoke_failed", "Smoke failed"),
])
def test_last_game_update_outcome_ignores_restores_and_reinstalls(farm, outcome, reason, label):
    from midgard_farm.gui.model import SessionModel

    farm.state()
    append_event(farm.platform, "game_update", classification="game_update", outcome=outcome, reason=reason)
    append_event(farm.platform, "game_update", action="restore_official", outcome="restored")
    append_event(farm.platform, "game_update", classification="game_reinstall", outcome="blocked")
    assert SessionModel(farm.platform).poll().updates.last_outcome == label


def test_update_controls_gate_active_sessions_and_show_correlated_restore_refusal(farm):
    from midgard_farm.gui.model import SessionModel

    farm.state("waiting_for_game", session_id="afk-fixture")
    model = SessionModel(farm.platform)
    assert model.poll().updates.action_blocker == "An AFK session is already active."
    assert model.patch_command("restore_official") is None
    assert model.patch_command("check_again") is None
    farm.state()
    assert model.patch_command("check_again")
    restore = model.patch_command("restore_official")
    assert restore
    farm.state(command_refusals=[
        {"request": "other", "command": "restore_official", "reason": "Someone else's request"},
        {"request": restore.name, "command": "restore_official",
         "reason": "Close the game before restoring the official patch."},
    ])
    assert model.poll().updates.feedback == "Restore refused: Close the game before restoring the official patch."


@pytest.mark.parametrize(("outcome", "message"), [
    ("restored", "Official patch restored."),
    ("restore_failed", "Could not restore the official patch: access denied"),
])
def test_updates_drops_restore_feedback_after_check_again(farm, outcome, message):
    from midgard_farm.gui.model import SessionModel

    farm.state()
    model = SessionModel(farm.platform)
    restore = model.patch_command("restore_official")
    assert restore
    result = {"request": restore.name, "outcome": outcome, "reason": message}
    farm.state(last_restore=result, keep_official=outcome == "restored")
    assert model.poll().updates.feedback == message
    assert model.patch_command("check_again")
    # Older service publications may still retain the outcome after the check.
    farm.state(last_restore=result, keep_official=False)
    assert model.poll().updates.feedback == ""


def test_bundled_main_qml_matches_source():
    from PySide6.QtCore import QFile, QIODevice

    from midgard_farm.gui import _resources  # noqa: F401  # Import registers the resource in Qt.

    source = Path(__file__).resolve().parents[1] / "src/midgard_farm/gui/Main.qml"
    resource = QFile(":/midgard-farm/Main.qml")
    assert resource.open(QIODevice.OpenModeFlag.ReadOnly), resource.errorString()
    assert bytes(resource.readAll()) == source.read_bytes(), "Regenerate _resources.py with pyside6-rcc"


@pytest.mark.parametrize("reason", ["build_failed", "anchors_broken", "smoke_failed"])
def test_rebuild_quarantine_offers_check_again(farm, reason):
    from midgard_farm.gui.model import SessionModel

    farm.state("farmer_unavailable", quarantine={"reason": reason, "detail": "Stopped before installation"})
    model = SessionModel(farm.platform)
    view = model.poll()
    assert not view.can_start and view.quarantine.action == "Check again"
    assert view.quarantine.can_check_again
    request = model.patch_command("check_again")
    assert request and commands.decode(json.loads(request.read_bytes())) == "check_again"


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QUICK_BACKEND", "software")
    if os.name == "nt" and not os.environ.get("QT_QPA_FONTDIR"):
        monkeypatch.setenv("QT_QPA_FONTDIR", str(Path(os.environ["SystemRoot"]) / "Fonts"))
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
    if item is None:
        pending = [window.contentItem()]
        while pending:
            child = pending.pop()
            if child.objectName() == name:
                return child
            pending.extend(child.childItems())
    assert item is not None, name
    return item


def wait_until(predicate):
    from PySide6.QtTest import QTest

    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, "Timed out waiting for the Qt window to update"
        QTest.qWait(20)


def capture(window, tmp_path, name):
    image = window.grabWindow()
    assert not image.isNull()
    assert image.save(str(tmp_path / f"{name}.png"))


def click(window, name):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    # A published snapshot can change visibility before Qt polishes the layout.
    assert not window.grabWindow().isNull()
    item = qml_item(window, name)
    assert item.property("visible") and item.property("enabled")
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=item.mapToScene(item.boundingRect().center()).toPoint())


def requested_commands(farm):
    return [commands.decode(json.loads(path.read_bytes()))
            for path in sorted(commands.directory(farm.platform).glob("*.json"))]


@pytest.fixture
def open_dashboard(qt_app, qt_warnings, farm):
    from PySide6.QtTest import QTest

    from midgard_farm.gui.model import SessionModel
    from midgard_farm.gui.window import load_window

    engine = window = None

    def open_tab(tab):
        nonlocal engine, window
        engine = load_window(SessionModel(farm.platform))
        [window] = engine.rootObjects()
        assert QTest.qWaitForWindowExposed(window)
        click(window, tab)
        return window

    yield open_tab
    if window is not None:
        window.close()
        engine = None
        qt_app.processEvents()
    assert not qt_warnings


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
        capture(window, tmp_path, screen)
        window.close()
    finally:
        del engine
        qt_app.processEvents()
    assert not qt_warnings


def test_afk_buttons_and_window_close(qt_app, qt_warnings, farm):
    from PySide6.QtTest import QTest

    from midgard_farm.gui.model import SessionModel
    from midgard_farm.gui.window import load_window

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


def test_history_screen_renders_interleaved_rows_and_expands_last_night(open_dashboard, farm, tmp_path):
    farm.state()
    history_fixture(farm)
    window = open_dashboard("historyTab")
    wait_until(lambda: qml_item(window, "historyRows").property("count") == 4)
    rows = [qml_item(window, f"historyRow{i}").property("text") for i in range(4)]
    assert "12 runs · 10 wins · 7,200 zeny" in rows[0]
    assert rows[1:3] == ["App update · Rolled back", "Game update · Handled"]
    assert "3 runs · 2 wins · 6,000 zeny" in rows[3]
    assert not qml_item(window, "lastNightDetails").property("visible")
    capture(window, tmp_path, "history")
    click(window, "lastNightDisclosure")
    assert qml_item(window, "lastNightDetails").property("visible")
    assert qml_item(window, "lastNightRewards").property("text").startswith("14,400 zeny")
    assert qml_item(window, "lastNightMaterials").property("text") == "Ore 4 · Star Crumb 2"
    capture(window, tmp_path, "history-expanded")


def test_history_screen_renders_empty_history(open_dashboard, farm, tmp_path):
    farm.state()
    window = open_dashboard("historyTab")
    assert qml_item(window, "historyRows").property("count") == 0
    capture(window, tmp_path, "history-empty")


@pytest.mark.parametrize(("classification", "kind", "title", "activity", "outcome", "reason", "last_outcome"), [
    ("current", "idle", "Current", "", "ready", "", "Handled"),
    ("game_update", "idle", "Game update", "", "quarantine", "build_failed", "Build failed"),
    ("farmer_removed_or_stale", "idle", "Farmer patch removed or stale", "", "quarantine", "anchors_broken", "Anchors broke"),
    ("game_reinstall", "farmer_unavailable", "Game reinstall", "", "blocked", "", "No outcome yet"),
    ("game_update", "waiting_for_game", "Game update", "Waiting for the game to close", "quarantine", "smoke_failed", "Smoke failed"),
    ("game_update", "rebuilding", "Game update", "Rebuilding", "ready", "", "Handled"),
])
def test_updates_screen_renders_states_and_outcomes(open_dashboard, farm, tmp_path, classification, kind,
                                                   title, activity, outcome, reason, last_outcome):
    from importlib.metadata import version

    farm.state(kind, game_update_classification=classification)
    append_event(farm.platform, "game_update", classification=classification, outcome=outcome, reason=reason)
    window = open_dashboard("updatesTab")
    wait_until(lambda: qml_item(window, "gameUpdateState").property("text") == title)
    assert qml_item(window, "gameUpdateOutcome").property("text") == last_outcome
    assert qml_item(window, "gameUpdateActivity").property("text") == activity
    guidance = qml_item(window, "gameUpdateDetail").property("text")
    assert ("Open the game" in guidance) == (classification == "game_reinstall")
    assert qml_item(window, "installedAppVersion").property("text") == version("midgard-farm")
    assert qml_item(window, "appUpdateCheck").property("text") == "No update check yet."
    suffix = kind if activity else classification
    capture(window, tmp_path, f"updates-{suffix.replace('_', '-')}")


def test_updates_buttons_submit_without_confirmation_and_restore_disables_during_session(
    open_dashboard, farm, tmp_path,
):
    farm.state(game_update_classification="current")
    window = open_dashboard("updatesTab")
    wait_until(lambda: qml_item(window, "restoreOfficialButton").property("enabled"))
    click(window, "checkAgainButton")
    click(window, "restoreOfficialButton")
    wait_until(lambda: requested_commands(farm) == ["check_again", "restore_official"])
    assert not qml_item(window, "abortDialog").property("visible")
    restore = sorted(commands.directory(farm.platform).glob("*.json"))[-1]
    result = {"request": restore.name, "outcome": "restored", "reason": "Official patch restored."}
    farm.state(game_update_classification="farmer_removed_or_stale", keep_official=True, last_restore=result,
               quarantine={"reason": "heartbeat_stale", "detail": "Previous session lost its heartbeat."})
    wait_until(lambda: qml_item(window, "gameUpdateState").property("text") == "Farmer patch removed or stale")
    assert qml_item(window, "patchFeedback").property("text") == result["reason"]
    capture(window, tmp_path, "updates-official-restored")
    click(window, "quarantineTab")
    assert not qml_item(window, "quarantineCheckFeedback").property("visible")
    click(window, "updatesTab")
    farm.state("active", session_id="afk-fixture", game_update_classification="current", last_restore=result)
    wait_until(lambda: not qml_item(window, "restoreOfficialButton").property("enabled"))
    assert qml_item(window, "patchActionBlocker").property("text") == "An AFK session is already active."
    assert not qml_item(window, "patchFeedback").property("visible")
    capture(window, tmp_path, "updates-session-active")


def test_quarantine_screen_renders_collapsed_diagnostics_and_links_to_afk(open_dashboard, farm, tmp_path):
    session = "afk-" + 32 * "2"
    logs = session_log_dir(farm.platform, session)
    logs.mkdir(parents=True)
    record = {"reason": "4 failures in 3600s", "detail": "No heartbeat for 15 seconds.",
              "attempts": [{"number": 4, "outcome": "failed", "reason": "heartbeat_stale"}]}
    record["diagnostics"] = logs.relative_to(farm.data).as_posix()
    (logs / "quarantine.json").write_text(json.dumps(record), encoding="utf-8")
    (logs / "attempt-04.log").touch()
    farm.state(quarantine=record, last_outcome={"kind": "quarantined", "session": session})
    window = open_dashboard("quarantineTab")
    wait_until(lambda: qml_item(window, "quarantineDetail").property("text") == record["detail"])
    assert not qml_item(window, "quarantineDiagnostics").property("visible")
    capture(window, tmp_path, "quarantine")
    click(window, "diagnosticsDisclosure")
    assert qml_item(window, "quarantineDiagnostics").property("visible")
    capture(window, tmp_path, "quarantine-expanded")
    click(window, "quarantineNextAction")
    assert qml_item(window, "screenTabs").property("currentIndex") == 0
    assert qml_item(window, "startButton").property("enabled")
    assert not requested_commands(farm)


@pytest.mark.parametrize(("reason", "title"), [
    ("build_failed", "Build failed"),
    ("anchors_broken", "Anchors broke"),
    ("smoke_failed", "Smoke failed"),
])
def test_quarantine_screen_retries_rebuild_reasons(open_dashboard, farm, tmp_path, reason, title):
    farm.state("farmer_unavailable", quarantine={"reason": reason, "detail": "Stopped before installation.",
                                                "log_path": str(farm.data / "rebuild.log")})
    window = open_dashboard("quarantineTab")
    wait_until(lambda: qml_item(window, "quarantineReason").property("text") == title)
    action = qml_item(window, "quarantineNextAction")
    assert action.property("text") == "Check again"
    capture(window, tmp_path, f"quarantine-{reason.replace('_', '-')}")
    click(window, "quarantineNextAction")
    wait_until(lambda: requested_commands(farm) == ["check_again"])


def test_quarantine_screen_renders_inactive_state(open_dashboard, farm, tmp_path):
    farm.state()
    window = open_dashboard("quarantineTab")
    assert qml_item(window, "noQuarantine").property("visible")
    capture(window, tmp_path, "quarantine-inactive")
