import json
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET

import pytest

from midgard_farm import platform
from midgard_farm.core.config import config_path, read_config
from midgard_farm.core.notify import Notifier


@pytest.fixture
def notification_data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return platform.current()


@pytest.mark.parametrize("event,priority", [
    ("fail", 3), ("quarantine", 3), ("stop", 3), ("goal", 3), ("game_update_handled", 2),
    ("build_failed", 4), ("anchors_broken", 4), ("smoke_failed", 4),
    ("app_update_rolled_back", 4),
])
def test_event_priority_reaches_both_transports(notification_data, monkeypatch, event, priority):
    os_ = notification_data
    path = config_path(os_)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"ntfy_url": "https://example.invalid/night", "future_field": True}))
    desktop, post = [], []

    class Response:
        def close(self):
            pass

    def send(request, *, timeout):
        post.append((request.full_url, request.headers["Priority"], request.data))
        return Response()

    monkeypatch.setattr(os_, "notify_desktop", lambda title, message, priority: desktop.append((title, message, priority)))
    monkeypatch.setattr("urllib.request.urlopen", send)
    notifier = Notifier(os_, read_config(os_).ntfy_url)
    notifier.notify(event, "Farm: ночь")
    notifier.drain()
    assert desktop == [(f"Midgard farmer: {event}", "Farm: ночь", {2: "low", 3: "normal", 4: "high"}[priority])]
    assert post == [("https://example.invalid/night", str(priority), "Farm: ночь".encode())]


def test_hung_desktop_does_not_hold_ntfy_or_bounded_drain(notification_data, monkeypatch):
    os_ = notification_data
    release, posted = threading.Event(), threading.Event()

    class Response:
        def close(self):
            posted.set()

    monkeypatch.setattr(os_, "notify_desktop", lambda *args: release.wait())
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    notifier = Notifier(os_, "https://example.invalid/night")
    try:
        notifier.notify("fail", "Retrying")
        assert posted.wait(2)
        notifier.drain(timeout=0.02)
        assert not release.is_set()
    finally:
        release.set()
        notifier.drain(timeout=2)


def test_no_config_or_bad_url_disables_only_ntfy(notification_data, monkeypatch):
    os_ = notification_data
    assert read_config(os_).ntfy_url == ""
    path = config_path(os_)
    path.parent.mkdir(parents=True)
    path.write_text('{"ntfy_url":"file:///etc/passwd"}')
    desktop, post = [], []
    monkeypatch.setattr(os_, "notify_desktop", lambda *args: desktop.append(args))
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: post.append(args))
    notifier = Notifier(os_, read_config(os_).ntfy_url)
    notifier.notify("stop", "Finished")
    notifier.drain()
    assert desktop == [("Midgard farmer: stop", "Finished", "normal")]
    assert post == []


def test_desktop_adapter_uses_native_transport_without_interpreting_message(monkeypatch):
    os_ = platform.current()
    invocation = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: invocation.append((argv, kwargs)))
    title, body = "Alert <1>", "$(not-a-command) & ночь"
    os_.notify_desktop(title, body, "high")
    (argv, options), = invocation
    assert options["timeout"] == 10
    assert options["check"]
    if sys.platform == "win32":
        assert argv[0].lower().endswith("powershell.exe")
        assert options["creationflags"] & 0x08000000  # CREATE_NO_WINDOW
        environment = options["env"]
        assert environment["MIDGARD_FARM_TOAST_PRIORITY"] == "high"
        xml = ET.fromstring(environment["MIDGARD_FARM_TOAST_XML"])
        assert [node.text for node in xml.findall("./visual/binding/text")] == [title, body]
    else:
        assert argv[0] == "notify-send"
        assert "--urgency=critical" in argv
        assert argv[-3:] == ["--", title, body]


def test_desktop_failure_is_logged_and_does_not_suppress_ntfy(notification_data, monkeypatch, capsys):
    delivered = threading.Event()

    def unavailable(*args):
        raise OSError("transport unavailable")

    class Response:
        def close(self):
            delivered.set()

    monkeypatch.setattr(notification_data, "notify_desktop", unavailable)
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    notifier = Notifier(notification_data, "https://example.invalid/night")
    notifier.notify("fail", "Supervisor retrying")
    notifier.drain()
    assert delivered.is_set()
    assert "desktop notification failed" in capsys.readouterr().out


def test_config_fields_are_validated_independently(notification_data, tmp_path):
    os_ = notification_data
    path = config_path(os_)
    path.parent.mkdir(parents=True)
    game_dir = tmp_path / "Midgard Survivors"
    path.write_text(json.dumps({"ntfy_url": "not a URL", "game_dir": str(game_dir)}))
    config = read_config(os_)
    assert config.ntfy_url == ""
    assert config.game_dir == game_dir

    path.write_text(json.dumps({"ntfy_url": "https://example.invalid/night", "game_dir": "relative"}))
    config = read_config(os_)
    assert config.ntfy_url == "https://example.invalid/night"
    assert config.game_dir is None
