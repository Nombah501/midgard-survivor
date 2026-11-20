"""Drive the installed service, update watchdog and release transport with fakes only."""

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from urllib.error import HTTPError

import pytest

from midgard_farm import assets, platform, service
from midgard_farm.core import _app_releases, app_update, commands, farmer_patch, patch_info, supervisor
from midgard_farm.core.history import read_history
from midgard_farm.core.farmer_patch import gdre
from midgard_farm.core.launch import AttemptExit
from midgard_farm.core.state import StateKind, StateReporter, read_state
from midgard_farm.gui.model import SessionModel
from test_game_update import UpdateFarm, farmer_sources, official_state, save_info, write_state
from test_profile import make_profile
from test_supervisor import wait_for


class FakePlatform(type(platform.current())):
    def __init__(self, root):
        self.root = root
        self.game = False
        self.notifications = []
        self.watchdogs = []
        self.restarts = []

    def app_data_dir(self):
        return self.root / "app data"

    def godot_user_data_root(self):
        return self.root / "profiles"

    def game_running(self):
        return self.game

    def check_network_isolation(self):
        return None

    def notify_desktop(self, title, message, priority):
        self.notifications.append((title, message, priority))

    def queue_update_watchdog(self, argv):
        self.watchdogs.append(list(argv))

    def clear_update_watchdog(self):
        pass

    def restart_service(self):
        self.restarts.append(current(self))

    def service_start_refused(self):
        return False


def bundle_path(os_, version):
    return os_.app_data_dir() / "versions" / version


def current(os_):
    return (os_.app_data_dir() / "current").read_text().strip()


def archive(os_, variant="good"):
    suffix = os_.executable_suffix
    files = {f"midgard-farm/midgard-farm-service{suffix}": b"service",
             f"midgard-farm/midgard-farm{suffix}": b"window",
             "midgard-farm/_internal/payload": b"data"}
    if variant == "traversal":
        files["midgard-farm/../../escaped"] = b"escape"
    output = io.BytesIO()
    if suffix:
        with zipfile.ZipFile(output, "w") as zip_:
            for name, data in files.items():
                zip_.writestr(name, data)
    else:
        with tarfile.open(fileobj=output, mode="w:gz") as tar:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), 0o755
                tar.addfile(member, io.BytesIO(data))
    return output.getvalue()


class FakeReleases:
    token = "fixture-secret-never-log"

    def __init__(self, os_):
        self.os = os_
        self.version = "2.0.0"
        self.status = 0
        self.corrupt = False
        self.unsafe = False
        self.hits = []
        self.asset_id = 11
        self.checksum_id = 12
        self.missing_checksum = False

    def open(self, request, *, timeout):
        url = request.full_url
        assert request.get_header("Authorization") == f"Bearer {self.token}"
        self.hits.append(url.rsplit("/", 1)[-1])
        if self.status:
            raise HTTPError(url, self.status, self.token, {}, None)
        platform_name = "windows-x86_64.zip" if self.os.executable_suffix else "linux-x86_64.tar.gz"
        name = f"midgard-farm-{self.version}-{platform_name}"
        body = archive(self.os, "traversal" if self.unsafe else "good")
        if url.endswith("/releases"):
            release_assets = [{"name": name, "id": self.asset_id}]
            if not self.missing_checksum:
                release_assets.append({"name": name + ".sha256", "id": self.checksum_id})
            payload = [{"tag_name": "v9.0.0rc1", "draft": False, "prerelease": False, "assets": []},
                       {"tag_name": "v8.0.0", "draft": False, "prerelease": True, "assets": []},
                       {"tag_name": "v" + self.version, "draft": False, "prerelease": False,
                        "assets": release_assets}]
            return io.BytesIO(json.dumps(payload).encode())
        assert request.get_header("Accept") == "application/octet-stream"
        if url.endswith(f"/{self.checksum_id}"):
            digest = "a" * 64 if self.corrupt else hashlib.sha256(body).hexdigest()
            return io.BytesIO(f"{digest}  {name}\n".encode())
        assert url.endswith(f"/{self.asset_id}")
        return io.BytesIO(body)


@pytest.fixture
def installed(tmp_path, monkeypatch):
    os_ = FakePlatform(tmp_path)
    profile = make_profile(os_.godot_user_data_root(), "Fixture Game")
    current_dir = bundle_path(os_, "1.0.0")
    current_dir.mkdir(parents=True)
    (current_dir / ("midgard-farm-service" + os_.executable_suffix)).touch()
    os_.write_atomic(os_.app_data_dir() / "current", b"1.0.0\n")
    os_.write_atomic(os_.app_data_dir() / "release-token", (FakeReleases.token + "\n").encode())
    releases = FakeReleases(os_)
    monkeypatch.setattr(platform, "current", lambda: os_)
    monkeypatch.setattr(_app_releases, "urlopen", releases.open)
    monkeypatch.setattr(app_update, "READY_TIMEOUT", 0.9)
    monkeypatch.setattr(app_update, "POLL", 0.02)
    monkeypatch.setattr(assets, "version", lambda: "1.0.0")
    return os_, profile, releases


@contextmanager
def running_service(monkeypatch):
    stopping = threading.Event()

    @contextmanager
    def shutdown():
        yield lambda: time.monotonic() if stopping.is_set() else None

    monkeypatch.setattr(service, "shutdown_request", shutdown)
    with ThreadPoolExecutor() as executor:
        future = executor.submit(service.main, [])
        try:
            yield future
        finally:
            stopping.set()
            assert future.result(timeout=5) == 0


def watchdog(os_):
    argv = os_.watchdogs[-1]
    assert Path(argv[0]).parent.name == "1.0.0"
    return service.main(argv[1:])


def test_awaits_closed_game_then_commits_after_selected_service_is_ready(installed, monkeypatch):
    os_, _, releases = installed
    os_.game = True
    extra = bundle_path(os_, "0.9.0")
    extra.mkdir()
    with running_service(monkeypatch) as old:
        wait_for(lambda: (bundle_path(os_, "2.0.0") / "_internal" / "payload").exists())
        assert current(os_) == "1.0.0" and not os_.watchdogs
        os_.game = False
        assert old.result(timeout=5) == 0
    assert current(os_) == "1.0.0"
    assert len(os_.watchdogs) == 1
    with ThreadPoolExecutor() as worker:
        applying = worker.submit(watchdog, os_)
        wait_for(lambda: os_.restarts == ["2.0.0"])
        data = os_.app_data_dir()
        switch = json.loads(os_.read_shared(data / "app-update-pending.json"))
        stale_instance = "f" * 32
        os_.write_atomic(data / "app-update-ready.json", json.dumps({
            "id": switch["id"], "version": "2.0.0", "pid": 99999999, "instance": stale_instance, "at": time.time(),
        }).encode())
        monkeypatch.setattr(assets, "version", lambda: "2.0.0")
        with running_service(monkeypatch):
            assert applying.result(timeout=5) == 0
            marker = json.loads(os_.read_shared(data / "app-update-ready.json"))
            assert marker["instance"] != stale_instance
            assert current(os_) == "2.0.0"
            assert sorted(p.name for p in bundle_path(os_, "1.0.0").parent.iterdir()) == ["1.0.0", "2.0.0"]
            wait_for(lambda: [row["outcome"] for row in read_history(os_) if row["kind"] == "app_update"],
                     lambda outcomes: outcomes == ["installed"])
    assert "11" in releases.hits and "12" in releases.hits


def test_stale_marker_cannot_prevent_rollback_and_bad_version_is_never_downloaded_again(installed, monkeypatch, capsys):
    os_, _, releases = installed
    with running_service(monkeypatch) as old:
        assert old.result(timeout=5) == 0
    (os_.app_data_dir() / "app-update-ready.json").write_text('{"version":"2.0.0","id":"stale"}')
    assert watchdog(os_) == 0
    assert current(os_) == "1.0.0"
    assert os_.restarts == ["2.0.0", "1.0.0"]
    assert any(message == "update to 2.0.0 rolled back" and priority == "high"
               for _, message, priority in os_.notifications)
    with running_service(monkeypatch):
        wait_for(lambda: releases.hits.count("releases") == 2)
        assert releases.hits.count("11") == 1
        assert len(os_.watchdogs) == 1
    assert FakeReleases.token not in (out := capsys.readouterr()).out + out.err


@pytest.mark.parametrize("status", [401, 403, 500])
def test_only_rejected_token_notifies_once_without_leaking_the_token(installed, monkeypatch, capsys, status):
    os_, _, releases = installed
    releases.status = status
    for attempt in (1, 2):
        with running_service(monkeypatch):
            wait_for(lambda: releases.hits.count("releases") == attempt)
    assert current(os_) == "1.0.0" and not os_.watchdogs
    assert sum("token_rejected" in title for title, *_ in os_.notifications) == (status in (401, 403))
    assert FakeReleases.token not in (out := capsys.readouterr()).out + out.err


@pytest.mark.parametrize("unsafe", [False, True])
def test_does_not_switch_to_corrupt_or_unsafe_release(installed, monkeypatch, unsafe):
    os_, _, releases = installed
    releases.corrupt, releases.unsafe = not unsafe, unsafe
    with running_service(monkeypatch):
        wait_for(lambda: app_update.read_update_status(os_).reason)
    assert current(os_) == "1.0.0"
    assert not bundle_path(os_, "2.0.0").exists() and not os_.watchdogs
    assert not (os_.app_data_dir() / "escaped").exists()


def test_service_checks_again_without_restarting_or_redownloading(installed, monkeypatch):
    os_, _, releases = installed
    os_.game = True
    monkeypatch.setattr(app_update, "CHECK_INTERVAL", 0.05)
    with running_service(monkeypatch):
        wait_for(lambda: releases.hits.count("releases") >= 3)
        assert releases.hits.count("11") == 1
        assert current(os_) == "1.0.0" and not os_.watchdogs


def test_verified_release_waits_for_afk_terminal_outcome_before_handoff(installed, monkeypatch, tmp_path):
    os_, profile, releases = installed
    patches = profile / "patches"
    official = official_state(profile)
    (patches / official["file"]).write_bytes(b"official patch")
    (patches / patch_info.INSTALLED_PACK).write_bytes(b"farmer patch")
    write_state(profile, official, "official-state.json")
    write_state(profile, official | {"file": patch_info.INSTALLED_PACK})
    save_info(os_)
    in_run, finish, response_allowed = threading.Event(), threading.Event(), threading.Event()
    open_release = releases.open

    def wait_for_fake_game(request, **kwargs):
        assert response_allowed.wait(timeout=5), "test did not release the fake HTTP response"
        return open_release(request, **kwargs)

    def farm_once(*args, **kwargs):
        in_run.set()
        assert finish.wait(timeout=5), "test did not let the fake farmer finish"
        status = {"phase": "done", "terminal": True, "finish_reason": "max_runs"}
        return AttemptExit(0, status, status, None)

    monkeypatch.setattr(_app_releases, "urlopen", wait_for_fake_game)
    monkeypatch.setattr(supervisor, "run_attempt", farm_once)
    request = commands.submit(os_, commands.Start(None, tmp_path / "preset.json"))
    with running_service(monkeypatch) as old:
        assert in_run.wait(timeout=5)
        response_allowed.set()
        wait_for(lambda: app_update.read_update_status(os_).staged == "2.0.0")
        assert not request.exists()
        assert read_state(os_).session_id and not read_state(os_).last_outcome
        assert current(os_) == "1.0.0" and not os_.watchdogs
        finish.set()
        assert old.result(timeout=5) == 0
    assert read_state(os_).last_outcome["reason"] == "max_runs"
    assert not (os_.app_data_dir() / "session.json").exists()
    assert Path(os_.watchdogs[0][0]).parent.name == "1.0.0"


@pytest.mark.parametrize("ready", [True, False])
def test_next_service_start_recovers_a_dead_watchdog(installed, monkeypatch, ready):
    os_, profile, _ = installed
    with running_service(monkeypatch) as old:
        assert old.result(timeout=5) == 0

    class SimulatedProcessDeath(BaseException):
        pass

    restart = os_.restart_service

    def die_after_pointer_switch():
        raise SimulatedProcessDeath

    monkeypatch.setattr(os_, "restart_service", die_after_pointer_switch)
    with pytest.raises(SimulatedProcessDeath):
        watchdog(os_)
    assert current(os_) == "2.0.0"
    assert not (os_.app_data_dir() / "app-update.json").exists()
    if not ready:
        (profile / "profile.json").unlink()
    monkeypatch.setattr(assets, "version", lambda: "2.0.0")
    monkeypatch.setattr(os_, "restart_service", restart)
    with running_service(monkeypatch):
        wait_for(lambda: len(os_.watchdogs) == 2)
        if ready:
            wait_for(lambda: (os_.app_data_dir() / "app-update-ready.json").exists())
        assert watchdog(os_) == 0
    assert current(os_) == ("2.0.0" if ready else "1.0.0")
    state = json.loads((os_.app_data_dir() / "app-update.json").read_bytes())
    assert ("2.0.0" in state.get("bad", [])) is not ready


def test_dying_before_pointer_publication_does_not_flag_the_release_bad(installed, monkeypatch):
    os_, _, _ = installed
    with running_service(monkeypatch) as old:
        assert old.result(timeout=5) == 0
    write = os_.write_atomic

    class PowerLoss(BaseException):
        pass

    def fail_pointer(path, value):
        if Path(path).name == "current":
            raise PowerLoss
        write(path, value)

    with monkeypatch.context() as crash:
        crash.setattr(os_, "write_atomic", fail_pointer)
        with pytest.raises(PowerLoss):
            watchdog(os_)
    assert current(os_) == "1.0.0"
    assert watchdog(os_) == 0
    state = os_.app_data_dir() / "app-update.json"
    assert not state.exists() or "2.0.0" not in json.loads(state.read_bytes()).get("bad", [])


def test_same_tag_new_asset_ids_recheck_the_archive(installed, monkeypatch):
    os_, _, releases = installed
    os_.game = True
    monkeypatch.setattr(app_update, "CHECK_INTERVAL", 0.05)
    with running_service(monkeypatch):
        wait_for(lambda: app_update.read_update_status(os_).staged == "2.0.0")
        releases.asset_id, releases.checksum_id = 13, 14
        wait_for(lambda: "13" in releases.hits and "14" in releases.hits, seconds=3)


def test_begin_reloads_stage_after_acquiring_update_lock(installed, monkeypatch):
    os_, _, _ = installed
    os_.game = True
    with running_service(monkeypatch):
        wait_for(lambda: app_update.read_update_status(os_).staged == "2.0.0")
    os_.game = False
    acquire = os_.acquire_lock

    def invalidate_stage_when_lock_is_taken(path):
        lock = acquire(path)
        if Path(path).name == "app-update.lock":
            (os_.app_data_dir() / "app-update-check.json").unlink(missing_ok=True)
        return lock

    monkeypatch.setattr(os_, "acquire_lock", invalidate_stage_when_lock_is_taken)
    updater = app_update.AppUpdater(os_, "1.0.0", lambda *_: None)
    assert updater.begin(manual=False) == (False, "")
    assert not os_.watchdogs
    assert current(os_) == "1.0.0"


@pytest.mark.parametrize("failure, reason", [("corrupt", "checksum did not match"),
                                            ("missing_checksum", "missing release archive or checksum")])
def test_failed_asset_replacement_invalidates_the_verified_stage(installed, monkeypatch, failure, reason):
    os_, _, releases = installed
    os_.game = True
    monkeypatch.setattr(app_update, "CHECK_INTERVAL", 0.05)
    with running_service(monkeypatch):
        wait_for(lambda: app_update.read_update_status(os_).staged == "2.0.0")
        setattr(releases, failure, True)
        releases.asset_id, releases.checksum_id = 13, 14
        status = wait_for(lambda: app_update.read_update_status(os_), lambda view: reason in view.reason)
        assert status.staged is None
        os_.game = False
        assert app_update.AppUpdater(os_, "1.0.0", lambda *_: None).begin(manual=False) == (False, "")
        assert not os_.watchdogs
        assert current(os_) == "1.0.0"


@pytest.mark.parametrize("had_started", [False, True])
def test_confirmed_scheduler_refusal_only_skips_blacklisting_an_unstarted_release(installed, monkeypatch, had_started):
    os_, _, _ = installed
    with running_service(monkeypatch) as old:
        assert old.result(timeout=5) == 0
    restart = os_.restart_service

    def record_start():
        if had_started and current(os_) == "2.0.0":
            data = os_.app_data_dir()
            switch = json.loads((data / "app-update-pending.json").read_bytes())
            os_.write_atomic(data / "app-update-started.json", json.dumps({"id": switch["id"]}).encode())
        restart()

    monkeypatch.setattr(os_, "restart_service", record_start)
    monkeypatch.setattr(os_, "service_start_refused", lambda: True, raising=False)
    assert watchdog(os_) == 0
    assert current(os_) == "1.0.0"
    state = json.loads((os_.app_data_dir() / "app-update.json").read_bytes())
    assert ("2.0.0" in state.get("bad", [])) is had_started
    assert any(msg == "update to 2.0.0 rolled back" for _, msg, _ in os_.notifications)


def test_stale_readiness_for_this_switch_requires_a_live_instance(installed, monkeypatch):
    os_, _, _ = installed
    with running_service(monkeypatch) as old:
        assert old.result(timeout=5) == 0
    restart = os_.restart_service

    def stale_readiness():
        if current(os_) == "2.0.0":
            data = os_.app_data_dir()
            switch = json.loads((data / "app-update-pending.json").read_bytes())
            marker = {"id": switch["id"], "version": "2.0.0", "pid": 99999999,
                      "instance": "f" * 32, "at": time.time()}
            os_.write_atomic(data / "app-update-ready.json", json.dumps(marker).encode())
        restart()

    monkeypatch.setattr(os_, "restart_service", stale_readiness)
    assert watchdog(os_) == 0
    assert current(os_) == "1.0.0"


def test_manual_rollback_without_readiness_restores_current_without_marking_target_bad(installed, monkeypatch):
    os_, _, _ = installed
    previous = bundle_path(os_, "0.9.0")
    previous.mkdir()
    (previous / ("midgard-farm-service" + os_.executable_suffix)).touch()
    os_.write_atomic(os_.app_data_dir() / "app-update.json", b'{"previous":"0.9.0"}')
    with running_service(monkeypatch) as old:
        commands.submit(os_, "rollback_app")
        assert old.result(timeout=5) == 0
    assert watchdog(os_) == 0
    assert current(os_) == "1.0.0"
    assert os_.restarts == ["0.9.0", "1.0.0"]
    assert any("rollback to 0.9.0 failed" in message and priority == "high" for _, message, priority in os_.notifications)
    assert json.loads((os_.app_data_dir() / "app-update.json").read_bytes()).get("bad", []) == []

def test_next_start_finishes_durable_rollback_after_the_watchdog_dies(installed, monkeypatch):
    os_, _, _ = installed
    with running_service(monkeypatch) as old:
        assert old.result(timeout=5) == 0

    class SimulatedProcessDeath(BaseException):
        pass

    restart = os_.restart_service

    def die_before_restarting_restored_service():
        if current(os_) == "1.0.0":
            raise SimulatedProcessDeath
        restart()

    monkeypatch.setattr(os_, "restart_service", die_before_restarting_restored_service)
    with pytest.raises(SimulatedProcessDeath):
        watchdog(os_)
    assert current(os_) == "1.0.0"
    pending = os_.app_data_dir() / "app-update-pending.json"
    assert pending.is_file()

    monkeypatch.setattr(os_, "restart_service", restart)
    with running_service(monkeypatch):
        wait_for(lambda: len(os_.watchdogs) == 2)
        assert watchdog(os_) == 0
        assert not pending.exists()
        wait_for(lambda: [row["outcome"] for row in read_history(os_) if row["kind"] == "app_update"])
    assert current(os_) == "1.0.0"
    assert [row["outcome"] for row in read_history(os_) if row["kind"] == "app_update"] == ["rolled back"]

def test_watchdog_recovers_a_notification_interrupted_after_persisting_rollback(installed, monkeypatch):
    os_, _, _ = installed
    with running_service(monkeypatch) as old:
        assert old.result(timeout=5) == 0

    class PowerLoss(BaseException):
        pass

    def die_before_notification(*_):
        raise PowerLoss

    identifier = os_.watchdogs[-1][-1]
    with pytest.raises(PowerLoss):
        app_update.run_watchdog(os_, identifier, die_before_notification)
    assert current(os_) == "1.0.0"
    assert watchdog(os_) == 0
    assert watchdog(os_) == 0
    assert sum("rolled back" in msg for _, msg, _ in os_.notifications) == 1


def test_update_history_is_written_only_by_the_service_holding_its_lock(installed, monkeypatch):
    os_, _, _ = installed
    with running_service(monkeypatch) as old:
        assert old.result(timeout=5) == 0
    assert watchdog(os_) == 0
    assert not [row for row in read_history(os_) if row["kind"] == "app_update"]
    with running_service(monkeypatch):
        wait_for(lambda: [row for row in read_history(os_) if row["kind"] == "app_update"])


def test_setup_and_watchdog_share_the_selection_lock(installed):
    from midgard_farm.core.install import install

    os_, _, _ = installed
    source = os_.root / "archive"
    for folder, names in ((source, ("midgard-farm", "midgard-farm-service", "midgard-farm-setup")),
                          (source / "launcher", ("midgard-farm-launcher",))):
        (folder / "_internal").mkdir(parents=True)
        for name in names:
            (folder / (name + os_.executable_suffix)).write_bytes(b"fixture")
    with os_.acquire_lock(os_.app_data_dir() / "app-update.lock"), pytest.raises(platform.LockHeld):
        install(os_, source, "3.0.0", lambda: pytest.fail("token already stored"))
    assert current(os_) == "1.0.0"


def test_watchdog_does_not_revert_or_prune_an_external_pointer_selection(installed, monkeypatch):
    os_, _, _ = installed
    with running_service(monkeypatch) as old:
        assert old.result(timeout=5) == 0
    third, previous = bundle_path(os_, "3.0.0"), bundle_path(os_, "0.9.0")
    third.mkdir()
    previous.mkdir()
    os_.write_atomic(os_.app_data_dir() / "app-update.json", b'{"previous":"0.9.0"}')
    restart = os_.restart_service

    def operator_selects_release():
        restart()
        os_.write_atomic(os_.app_data_dir() / "current", b"3.0.0\n")

    monkeypatch.setattr(os_, "restart_service", operator_selects_release)
    assert watchdog(os_) == 0
    assert current(os_) == "3.0.0"
    assert third.exists() and previous.exists()
    assert os_.restarts == ["2.0.0"]


def test_active_supervisor_keeps_rollback_in_service_queue(installed, monkeypatch):
    from types import SimpleNamespace

    os_, profile, _ = installed
    monkeypatch.setattr(supervisor, "log", lambda *_: None)
    queued = commands.submit(os_, "rollback_app")
    driver = supervisor.Supervisor(os_, profile, supervisor.Policy(), lambda: None, lambda *_: None,
                                  state=SimpleNamespace())
    assert not list(driver._pending())
    assert queued.exists()



def test_manual_rollback_restarts_previous_version_and_does_not_reinstall_current(installed, monkeypatch):
    os_, _, releases = installed
    new = bundle_path(os_, "2.0.0")
    new.mkdir()
    (new / ("midgard-farm-service" + os_.executable_suffix)).touch()
    os_.write_atomic(os_.app_data_dir() / "current", b"2.0.0\n")
    os_.write_atomic(os_.app_data_dir() / "app-update.json", b'{"previous":"1.0.0"}')
    monkeypatch.setattr(assets, "version", lambda: "2.0.0")
    os_.game = True
    with running_service(monkeypatch) as latest:
        assert service.main(["rollback-app"]) == 0
        wait_for(lambda: read_state(os_).reason == "waiting for the game to close")
        assert not os_.watchdogs
        os_.game = False
        assert latest.result(timeout=5) == 0
    assert Path(os_.watchdogs[-1][0]).parent == new
    with ThreadPoolExecutor() as worker:
        rollback = worker.submit(service.main, os_.watchdogs[-1][1:])
        wait_for(lambda: os_.restarts == ["1.0.0"])
        assert app_update.read_update_status(os_).previous == "1.0.0"
        monkeypatch.setattr(assets, "version", lambda: "1.0.0")
        previous_checks = releases.hits.count("releases")
        with running_service(monkeypatch):
            assert rollback.result(timeout=5) == 0
            assert current(os_) == "1.0.0"
            assert app_update.read_update_status(os_).previous == "2.0.0"
            wait_for(lambda: releases.hits.count("releases") > previous_checks)
    assert releases.hits.count("11") == 0 and len(os_.watchdogs) == 1


def test_updates_view_shows_check_failures_and_dispatches_rollback(installed):
    os_, _, _ = installed
    os_.write_atomic(os_.app_data_dir() / "app-update.json", b'{"previous":"0.9.0"}')
    os_.write_atomic(os_.app_data_dir() / "app-update-check.json", b'{"reason":"GitHub returned HTTP 500"}')
    with StateReporter(os_) as state:
        state.set(StateKind.IDLE)
        model = SessionModel(os_)
        view = model.poll().updates
        assert view.app_version == "1.0.0"
        assert "GitHub returned HTTP 500" in view.app_check
        assert view.can_rollback
        request = model.rollback_app()
        assert commands.decode(json.loads(request.read_bytes())) == "rollback_app"
        assert not model.poll().updates.can_rollback


def test_app_switch_and_rollback_rebuild_only_for_the_selected_farmer_hash(installed, monkeypatch, tmp_path):
    os_, profile, _ = installed
    game = UpdateFarm(tmp_path, profile, monkeypatch)
    monkeypatch.setattr(os_, "game_exe_name", game.os.game_exe_name)
    monkeypatch.setattr(os_, "spawn_tree", game.os.spawn_tree)
    monkeypatch.setattr(gdre, "prepare", lambda *_: game.gdre)
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["pass","pass"]')
    old_sources, new_sources = tmp_path / "old farmer", tmp_path / "new farmer"
    farmer_sources(old_sources)
    new_script = farmer_sources(new_sources)
    with new_script.open("a", encoding="utf-8") as file:
        file.write("\n# release changed the farmer inputs\n")
    build = import_module("midgard_farm.core.farmer_patch.build")
    monkeypatch.setattr(build, "_SOURCE_DIR", old_sources)
    old_hash = farmer_patch.farmer_hash()
    farmer_patch.build(os_, profile, gdre=game.gdre)
    farmer_patch.install(os_, profile)
    assert patch_info.load(patch_info.info_path(os_)).farmer_hash == old_hash

    with running_service(monkeypatch) as old:
        assert old.result(timeout=5) == 0
    with ThreadPoolExecutor() as workers:
        updating = workers.submit(watchdog, os_)
        wait_for(lambda: os_.restarts == ["2.0.0"])
        monkeypatch.setattr(assets, "version", lambda: "2.0.0")
        monkeypatch.setattr(build, "_SOURCE_DIR", new_sources)
        new_hash = farmer_patch.farmer_hash()
        with running_service(monkeypatch) as new:
            assert updating.result(timeout=5) == 0
            wait_for(lambda: [row.get("farmer_hash") for row in read_history(os_) if row["kind"] == "game_update"],
                     lambda hashes: hashes == [new_hash])
            commands.submit(os_, "rollback_app")
            assert new.result(timeout=5) == 0
    with ThreadPoolExecutor() as worker:
        rollback = worker.submit(service.main, os_.watchdogs[-1][1:])
        wait_for(lambda: os_.restarts == ["2.0.0", "1.0.0"])
        monkeypatch.setattr(assets, "version", lambda: "1.0.0")
        monkeypatch.setattr(build, "_SOURCE_DIR", old_sources)
        with running_service(monkeypatch):
            assert rollback.result(timeout=5) == 0
            wait_for(lambda: [row.get("farmer_hash") for row in read_history(os_) if row["kind"] == "game_update"],
                     lambda hashes: hashes == [new_hash, old_hash])
    assert patch_info.load(patch_info.info_path(os_)).farmer_hash == old_hash
    assert [record["stage"] for record in game.observations()] == ["build", "build", "smoke", "build", "smoke"]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux user service activation")
def test_linux_watchdog_queues_an_independent_bounded_user_unit(monkeypatch):
    calls = []

    def fake_system_tool(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="Result=start-limit-hit\nActiveState=failed\nNRestarts=0\n")

    monkeypatch.setattr(subprocess, "run", fake_system_tool)
    os_ = platform.current()
    argv = ["/tmp/Midgard Farm/versions/1.0.0/midgard-farm-service", "--app-update-handoff", "fixture"]
    os_.queue_update_watchdog(argv)
    os_.restart_service()
    assert os_.service_start_refused()
    assert calls[0][:4] == ["systemd-run", "--user", "--no-block", "--collect"]
    assert "--property=RuntimeMaxSec=120s" in calls[0]
    assert calls[0][-4:] == ["--", *argv]
    assert calls[1:3] == [
        ["systemctl", "--user", "reset-failed", "midgard-farm.service"],
        ["systemctl", "--user", "restart", "--no-block", "midgard-farm.service"],
    ]
    assert calls[3] == ["systemctl", "--user", "show", "--property=Result", "--property=ActiveState",
                        "--property=NRestarts", "midgard-farm.service"]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux user service activation")
def test_linux_restart_still_queues_when_stopped_unit_has_been_unloaded(monkeypatch):
    calls = []

    def fake_system_tool(args, **kwargs):
        calls.append(args)
        if "reset-failed" in args:
            raise subprocess.CalledProcessError(1, args, stderr="Unit midgard-farm.service not loaded.")
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_system_tool)
    platform.current().restart_service()
    assert calls[-1] == ["systemctl", "--user", "restart", "--no-block", "midgard-farm.service"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows user Task Scheduler")
def test_windows_watchdog_is_a_separate_bounded_unprivileged_on_demand_task(monkeypatch, tmp_path):
    from xml.etree import ElementTree

    from midgard_farm.platform import windows

    commands_run, task = [], []

    def fake_system_tool(tool, *args):
        if tool == "whoami.exe":
            return '"PC\\user","S-1-5-21-123-456-789-1001"\n'
        assert tool == "schtasks.exe"
        commands_run.append(args)
        if args[0] == "/Create":
            task.append(ElementTree.fromstring(Path(args[4]).read_text(encoding="utf-16")))
        return ""

    monkeypatch.setattr(windows, "_system_tool", fake_system_tool)
    os_ = platform.current()
    executable = str(tmp_path / "versions" / "1.0.0" / "midgard-farm-service.exe")
    os_.queue_update_watchdog([executable, "--app-update-handoff", "fixture"])
    os_.restart_service()
    os_.clear_update_watchdog()
    assert task[0].find(".//{*}Triggers") is None
    assert task[0].findtext(".//{*}Principal/{*}RunLevel") == "LeastPrivilege"
    assert task[0].findtext(".//{*}Settings/{*}ExecutionTimeLimit") == "PT120S"
    assert task[0].findtext(".//{*}Exec/{*}Command") == executable
    assert commands_run[1:] == [
        ("/Run", "/TN", "Midgard Farm App Update"),
        ("/End", "/TN", "Midgard Farm"), ("/Run", "/TN", "Midgard Farm"),
        ("/Delete", "/TN", "Midgard Farm App Update", "/F"),
    ]
