"""Exercise Doctor against isolated app data, profiles and service fixtures."""

import hashlib
import json
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest

from midgard_farm import doctor as cli, platform
from midgard_farm.core import _app_releases, doctor, game_update, patch_info
from midgard_farm.core.config import config_path
from midgard_farm.core.farmer_patch import farmer_hash, gdre
from midgard_farm.core.history import read_history
from midgard_farm.core.state import StateKind, read_state, state_path
from test_game_update import farm, snapshot, update_profile, write_state  # noqa: F401 - pytest fixtures
from test_game_update_service import RUNNER, update_service
from test_profile import make_profile
from test_supervisor import wait_for


@pytest.fixture
def ready_farm(farm, monkeypatch):
    pack = b"previously built farmer pack"
    state = json.loads((farm.patches / "state.json").read_bytes())
    write_state(farm.profile, state, "official-state.json")
    write_state(farm.profile, state | {"file": patch_info.INSTALLED_PACK, "farmer": 1})
    (farm.patches / patch_info.INSTALLED_PACK).write_bytes(pack)
    info = patch_info.PatchInfo(
        patch_file=state["file"], patch_version=state["version"],
        patch_sha256=hashlib.sha256((farm.patches / state["file"]).read_bytes()).hexdigest(),
        bridge_file="bridge.pck",
        bridge_sha256=hashlib.sha256((farm.patches / "bridge.pck").read_bytes()).hexdigest(),
        bytecode="ebc36a7", farmer_api=3, farmer_hash=farmer_hash(),
        result_sha256=hashlib.sha256(pack).hexdigest(), built_at="2026-01-01T00:00:00Z",
    )
    patch_info.save(farm.os, patch_info.info_path(farm.os), info)
    patch_info.built_pack_path(farm.os).write_bytes(pack)
    monkeypatch.setattr(farm.os, "service_registered", lambda: True)
    monkeypatch.setattr(farm.os, "check_network_isolation", lambda: None)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(free=2**40))
    monkeypatch.delenv("FARMER_MIN_FREE_MB", raising=False)
    state_path(farm.os).write_text(json.dumps({"kind": "idle", "updated_at": time.time()}))
    config_path(farm.os).write_text(json.dumps({"ntfy_url": "https://ntfy.example/private-topic"}))
    monkeypatch.setattr(_app_releases, "UPDATE_BASE_URL", "https://updates.example")
    monkeypatch.setattr(
        _app_releases, "MINISIGN_PUBLIC_KEY", "RWRoZWFsdGh5ITExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTEx",
    )
    release = gdre.RELEASES[farm.os.release_os]
    cached = gdre.cached_archive(farm.os)
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"abc")
    monkeypatch.setitem(gdre.RELEASES, farm.os.release_os, gdre.Release(
        release.url, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", release.executable,
    ))
    return farm


def checks(os_):
    return {row["id"]: row for row in doctor.run_checks(os_)}


def test_healthy_diagnostics_are_read_only_and_do_not_disclose_notification_url(ready_farm):
    farm = ready_farm
    before = snapshot(farm.profile), snapshot(farm.os.app_data_dir())

    report = checks(farm.os)

    assert set(report) == {
        "game_install", "profile", "official_patch", "farmer_patch", "gdre", "network_isolation", "service",
        "app_disk", "profile_disk", "notifications", "update_channel", "quarantine",
    }
    assert all(row["status"] == "ok" and row["next_action"] == "" for row in report.values())
    assert "private-topic" not in str(report)
    assert (snapshot(farm.profile), snapshot(farm.os.app_data_dir())) == before


def test_missing_game_gives_discovery_guidance(ready_farm):
    farm = ready_farm
    farm.os.game_executable().unlink()
    row = checks(farm.os)["game_install"]
    assert row["status"] == "fail"
    assert "GAME_DIR" in row["next_action"]


@pytest.mark.parametrize("ambiguous", [False, True])
def test_profile_discovery_never_guesses(ready_farm, ambiguous):
    farm = ready_farm
    if ambiguous:
        make_profile(farm.os.godot_user_data_root(), "Second profile")
    else:
        (farm.profile / "profile.json").unlink()
    report = checks(farm.os)
    assert report["profile"]["status"] == "fail"
    assert ("archive" if ambiguous else "once") in report["profile"]["next_action"].lower()
    assert report["profile_disk"]["status"] == "warn"
    assert report["official_patch"]["status"] == report["farmer_patch"]["status"] == "warn"


def test_missing_official_patch_requires_game_update(ready_farm):
    farm = ready_farm
    (farm.patches / "official.pck").unlink()
    report = checks(farm.os)
    assert report["official_patch"]["status"] == "fail"
    assert "accept" in report["official_patch"]["next_action"]
    assert report["farmer_patch"]["status"] == "warn"


@pytest.mark.parametrize(("file", "hint"), [
    ("official.pck", "official patch"), ("bridge.pck", "bridge"), (patch_info.INSTALLED_PACK, "installed"),
])
def test_digests_detect_same_name_replacements(ready_farm, file, hint):
    farm = ready_farm
    (farm.patches / file).write_bytes(b"replacement")
    report = checks(farm.os)
    assert report["official_patch"]["status"] == "ok"
    row = report["farmer_patch"]
    assert row["status"] == "fail"
    assert hint in row["summary"].lower()
    assert "Repair farmer pack" in row["next_action"]


def test_invalid_official_state_is_not_a_repairable_digest_mismatch(ready_farm):
    farm = ready_farm
    write_state(farm.profile, {"file": "../not-a-pack"}, "official-state.json")
    report = checks(farm.os)
    assert report["official_patch"]["status"] == "fail"
    assert report["farmer_patch"]["status"] == "warn"


@pytest.mark.parametrize(("cache", "status"), [(None, "warn"), (b"corrupt", "fail")])
def test_gdre_reports_absent_or_corrupt_cache_without_downloading(ready_farm, monkeypatch, cache, status):
    farm = ready_farm
    path = gdre.cached_archive(farm.os)
    if cache is None:
        path.unlink()
    else:
        path.write_bytes(cache)
    monkeypatch.setattr(gdre, "urlopen", lambda *args, **kwargs: pytest.fail("unexpected download"))
    row = checks(farm.os)["gdre"]
    assert row["status"] == status
    assert "GitHub" in row["next_action"]
    assert not path.exists() if cache is None else path.read_bytes() == cache


def test_namespace_failure_and_windows_host_network_warning(ready_farm, monkeypatch):
    farm = ready_farm

    def namespace_denied():
        raise OSError("unshare: operation not permitted")

    monkeypatch.setattr(farm.os, "check_network_isolation", namespace_denied)
    assert checks(farm.os)["network_isolation"]["status"] == "fail"
    monkeypatch.setattr(farm.os, "check_network_isolation", lambda: "Game runs on the Windows host network.")
    notice = checks(farm.os)["network_isolation"]
    assert notice["status"] == "warn"
    assert "cloud" in notice["next_action"].lower()


def test_service_must_be_registered_and_publish_fresh_state(ready_farm, monkeypatch):
    farm = ready_farm
    monkeypatch.setattr(farm.os, "service_registered", lambda: False)
    row = checks(farm.os)["service"]
    assert row["status"] == "fail" and "setup" in row["next_action"]
    monkeypatch.setattr(farm.os, "service_registered", lambda: True)
    state_path(farm.os).write_text('{"kind":"idle","updated_at":0}')
    row = checks(farm.os)["service"]
    assert row["status"] == "fail" and "Start service" in row["next_action"]


@pytest.mark.parametrize("volume", ["app_disk", "profile_disk"])
def test_low_disk_is_reported_on_the_correct_volume(ready_farm, monkeypatch, volume):
    farm = ready_farm
    low = farm.os.app_data_dir() if volume == "app_disk" else farm.profile
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(free=0 if path == low else 2**40))
    report = checks(farm.os)
    assert report[volume]["status"] == "fail"
    assert report["profile_disk" if volume == "app_disk" else "app_disk"]["status"] == "ok"


def test_optional_notification_configuration_and_invalid_values(ready_farm):
    farm = ready_farm
    config_path(farm.os).unlink()
    assert checks(farm.os)["notifications"]["status"] == "warn"
    config_path(farm.os).write_text('{"ntfy_url":"file:///secret"}')
    row = checks(farm.os)["notifications"]
    assert row["status"] == "fail"
    assert "ntfy_url" in row["next_action"] and "secret" not in str(row)


@pytest.mark.parametrize(("field", "value"), [
    ("UPDATE_BASE_URL", "https://replace-with-operator-updates-domain.invalid"), ("MINISIGN_PUBLIC_KEY", ""),
])
def test_unprovisioned_update_channel_is_reported_without_network(ready_farm, monkeypatch, field, value):
    monkeypatch.setattr(_app_releases, field, value)
    monkeypatch.setattr(_app_releases, "get_manifest", lambda: pytest.fail("unexpected update fetch"))
    row = checks(ready_farm.os)["update_channel"]
    assert row["status"] == "warn"
    assert "ADR 0010" in row["next_action"]


@pytest.mark.parametrize(("reason", "guidance"), [
    ("smoke_failed", "Check again"), ("flush_failed", "save"), ("invalid_oath", "run choice"),
    ("preflight_failed", "Doctor checks"),
    ("4 failures in 3600s", "logs"),
])
def test_quarantine_maps_fix_and_uses_disk_record_if_service_unavailable(ready_farm, reason, guidance):
    farm = ready_farm
    state_path(farm.os).unlink()
    (farm.os.app_data_dir() / "quarantine.json").write_text(json.dumps({"reason": reason}))
    row = checks(farm.os)["quarantine"]
    assert row["status"] == "fail"
    assert reason in row["summary"] and guidance in row["next_action"]


def test_cli_prints_failure_summary_and_never_repairs(ready_farm, monkeypatch, capsys):
    farm = ready_farm
    monkeypatch.setattr(cli.platform, "current", lambda: farm.os)
    (farm.patches / patch_info.INSTALLED_PACK).unlink()

    assert cli.main([]) == 1
    out = capsys.readouterr().out
    assert "OK [official_patch]" in out and "FAIL [farmer_patch]" in out
    assert "Repair farmer pack" in out
    assert not (farm.os.app_data_dir() / "commands").exists()


@pytest.mark.parametrize("busy", ["game", "session", "saved", "service"])
def test_repair_does_not_queue_when_unsafe(ready_farm, busy):
    farm = ready_farm
    message = {
        "game": "Close the game", "session": "Finish the AFK session", "saved": "unfinished AFK session",
        "service": "running and idle",
    }[busy]
    if busy == "game":
        farm.running.touch()
    elif busy == "session":
        state_path(farm.os).write_text(json.dumps({
            "kind": "waiting_for_game", "session_id": "afk-test", "updated_at": time.time(),
        }))
    elif busy == "saved":
        (farm.os.app_data_dir() / "session.json").write_text("{}")
    else:
        state_path(farm.os).unlink()
    before = snapshot(farm.profile)

    with pytest.raises(doctor.RepairUnavailable, match=message):
        doctor.repair_farmer_pack(farm.os)

    assert not (farm.os.app_data_dir() / "commands").exists()
    assert snapshot(farm.profile) == before


@pytest.mark.parametrize(("damaged", "new_stages"), [
    (patch_info.INSTALLED_PACK, []),
    ("bridge.pck", ["build", "smoke"]),
    ("official.pck", ["build", "smoke"]),
])
def test_explicit_repair_is_dispatched_to_the_service_without_touching_saves(
    update_service, monkeypatch, damaged, new_stages,
):
    farm, update, _, _ = update_service
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["pass", "pass"]')
    saves = {name: (farm.profile / name).read_bytes() for name in ("profile.json", "profile.run")}
    with farm.service(runner=RUNNER):
        wait_for(lambda: read_history(farm.os_))
        wait_for(lambda: read_state(farm.os_), lambda state: state.kind is StateKind.IDLE)
        path = update.patches / damaged
        # Whitespace also changes the official fake pack's digest while preserving its contents.
        path.write_bytes(path.read_bytes() + b"\n")
        assert game_update.classify(farm.os_, farm.profile) is game_update.GameUpdateState.CURRENT

        request = doctor.repair_farmer_pack(farm.os_)
        wait_for(lambda: not request.exists())
        assert [event["outcome"] for event in read_history(farm.os_)] == ["ready", "ready"]
        patch = game_update.inspect_patch(farm.os_, farm.profile)
        assert patch is not None and patch.integrity_issue() is None
        assert not farm.plan.with_suffix(".count").exists()

    assert [entry["stage"] for entry in update.observations()] == ["build", "smoke", *new_stages]
    assert {name: (farm.profile / name).read_bytes() for name in saves} == saves


def test_ordinary_current_check_does_not_hash_packs(ready_farm, monkeypatch):
    farm = ready_farm
    (farm.patches / patch_info.INSTALLED_PACK).write_bytes(b"corrupt")
    monkeypatch.setattr(game_update, "sha256", lambda path: pytest.fail(f"idle check hashed {path}"))
    assert isinstance(farm.pipeline().run(), game_update.Ready)


@pytest.mark.parametrize("allow_digest_repair", [True, False])
def test_explicit_check_waits_for_game_close_but_never_repairs_during_a_session(ready_farm, allow_digest_repair):
    farm = ready_farm
    pipeline = farm.pipeline(close_grace_seconds=0)
    installed = farm.patches / patch_info.INSTALLED_PACK
    good = installed.read_bytes()
    installed.write_bytes(b"corrupt")
    farm.running.touch()
    assert isinstance(pipeline.run(check_again=True), game_update.Wait)
    assert installed.read_bytes() == b"corrupt"

    farm.running.unlink()
    assert isinstance(pipeline.run(allow_digest_repair=allow_digest_repair), game_update.Ready)
    assert installed.read_bytes() == (good if allow_digest_repair else b"corrupt")


@pytest.mark.skipif(platform.current().release_os != "linux", reason="native user-unit query")
def test_linux_service_registration_probe_reads_systemd_load_state(game_platform, monkeypatch):
    results = iter(["loaded\n", "not-found\n"])

    def show(*args):
        assert args == ("show", "--property=LoadState", "--value", "midgard-farm.service")
        return next(results)

    monkeypatch.setattr(game_platform, "_systemctl", show)
    assert game_platform.service_registered() is True
    assert game_platform.service_registered() is False


@pytest.mark.skipif(platform.current().release_os != "windows", reason="native Windows discovery")
def test_windows_executable_discovery_does_not_learn_or_overwrite_location(tmp_path, game_platform, monkeypatch):
    from midgard_farm.platform import windows

    monkeypatch.delenv("GAME_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "App data"))
    game = tmp_path / game_platform.game_exe_name
    game.touch()
    monkeypatch.setattr(game_platform, "game_pids", lambda: {123})
    monkeypatch.setattr(windows, "_process_image", lambda pid: game)
    assert game_platform.game_executable_readonly() == game
    assert not game_platform.app_data_dir().exists()

    record = game_platform.app_data_dir() / "game-executable.txt"
    record.parent.mkdir(parents=True)
    record.write_text(str(game), encoding="utf-8")
    monkeypatch.setattr(game_platform, "game_pids", lambda: pytest.fail("known location should be used first"))
    assert game_platform.game_executable_readonly() == game
    configured = tmp_path / "Configured game"
    config_path(game_platform).write_text(json.dumps({"game_dir": str(configured)}), encoding="utf-8")
    assert game_platform.game_executable_readonly() == configured / game_platform.game_exe_name
    monkeypatch.setenv("GAME_DIR", str(tmp_path))
    assert game_platform.game_executable_readonly() == game
    assert record.read_text(encoding="utf-8") == str(game)


@pytest.mark.skipif(platform.current().release_os != "windows", reason="native Task Scheduler query")
def test_windows_service_registration_queries_task_without_mutation(game_platform, monkeypatch):
    from midgard_farm.platform import windows

    def query(*args):
        assert args == ("schtasks.exe", "/Query", "/TN", windows.SERVICE_TASK_NAME, "/XML")
        return "<Task/>"

    monkeypatch.setattr(windows, "_system_tool", query)
    assert game_platform.service_registered() is True

    def missing(*args):
        query(*args)
        raise subprocess.CalledProcessError(1, args, stderr=windows.ctypes.FormatError(windows.ERROR_FILE_NOT_FOUND))

    monkeypatch.setattr(windows, "_system_tool", missing)
    assert game_platform.service_registered() is False
