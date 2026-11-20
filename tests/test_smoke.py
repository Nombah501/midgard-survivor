"""Exercise the smoke module with a sandbox and an out-of-process fake game."""

import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from midgard_farm import platform
from midgard_farm.core import patch_info, smoke
from test_platform import lock_freed_within
from test_profile import godot_root, make_profile

_ORIGINAL_SAVE = '{"zeny":100}'


class FakeGamePlatform(type(platform.current())):
    use_real_isolation = False

    def spawn_tree(self, argv, *, isolate_network=False, **kwargs):
        assert isolate_network, "the smoke game must request network isolation"
        fake = Path(__file__).with_name("fake_smoke_game.py")
        return super().spawn_tree(
            [sys.executable, str(fake), *argv[1:]], isolate_network=self.use_real_isolation, **kwargs,
        )


@pytest.fixture
def setup_smoke(tmp_path, monkeypatch, fake_game_name):
    home = tmp_path / "real data"
    for name in ("XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(home))
    monkeypatch.setenv("FARMER_DISPLAY", "1")  # Never overrides the smoke preset.
    monkeypatch.setenv("GAME_DIR", str(tmp_path / "fake game install"))
    os_ = FakeGamePlatform()
    os_.game_exe_name = fake_game_name
    exe = os_.game_executable()
    exe.parent.mkdir()
    exe.touch()
    exe.chmod(0o755)
    profile = make_profile(godot_root(home), "Renamed Game Profile")
    monkeypatch.setenv("FAKE_SMOKE_PROFILE", str(profile))
    records = tmp_path / "fake game records"
    records.mkdir()
    monkeypatch.setenv("FAKE_SMOKE_RECORDS", str(records))

    (profile / "profile.json").write_text(_ORIGINAL_SAVE, encoding="utf-8")
    (profile / "profile.run").write_bytes(b"real run save")
    (profile / "farmer_stop").touch()
    (profile / "farmer_status.json").write_text('{"phase":"done"}', encoding="utf-8")
    (profile / "farmer.log").write_text("old FINISH marker", encoding="utf-8")
    (profile / "farmer_runs.jsonl").write_text("old journal", encoding="utf-8")
    patches = profile / "patches"
    # Exercise rebuilding an already mounted farmer patch (a Farmer hash change).
    state = {"file": "official.pck", "base": "base.pck", "version": "1", "bridge": {"file": "bridge.pck"}}
    (patches / "official-state.json").write_text(json.dumps(state), encoding="utf-8")
    (patches / "state.json").write_text(
        json.dumps(state | {"file": patch_info.INSTALLED_PACK, "farmer": 1}), encoding="utf-8",
    )
    (patches / patch_info.INSTALLED_PACK).write_bytes(b"old farmer")
    official = b"official bytes" * 1_600_000  # Larger than verify.sh's 20 MB link threshold.
    bridge = b"bridge bytes"
    candidate = b"candidate farmer"
    (patches / "official.pck").write_bytes(official)
    (patches / "bridge.pck").write_bytes(bridge)
    patch_info.save(os_, patch_info.info_path(os_), patch_info.PatchInfo(
        patch_file="official.pck", patch_version="1", patch_sha256=hashlib.sha256(official).hexdigest(),
        bridge_file="bridge.pck", bridge_sha256=hashlib.sha256(bridge).hexdigest(),
        bytecode="ebc36a7", farmer_api=3, farmer_hash="fixture", result_sha256=hashlib.sha256(candidate).hexdigest(),
        built_at="2026-01-01T00:00:00Z",
    ))
    patch_info.built_pack_path(os_).write_bytes(candidate)
    return os_, profile, records


def _snapshot(profile):
    return {
        path.relative_to(profile): (path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns)
        for path in (profile, *profile.rglob("*"))
    }


@pytest.mark.parametrize("farmer_mounted", [False, True])
def test_smoke_mounts_and_plays_only_in_sandbox(setup_smoke, farmer_mounted):
    os_, profile, records = setup_smoke
    if not farmer_mounted:
        patches = profile / "patches"
        (patches / "official-state.json").replace(patches / "state.json")
        (patches / patch_info.INSTALLED_PACK).unlink()
    before = _snapshot(profile)

    result = smoke.run_smoke(os_, profile)

    assert result.outcome is smoke.SmokeOutcome.PASSED
    assert result.passed and result.attempts == 1
    assert {"fake stdout", "fake stderr"} <= set(result.log_path.read_text().splitlines())
    record = json.loads((records / "attempt-1.json").read_text(encoding="utf-8"))
    assert record["original_save"] == _ORIGINAL_SAVE
    assert record["candidate"] == "candidate farmer"
    assert record["mounted"] == {
        "file": "patch_farmer.pck", "base": "base.pck", "version": "1", "bridge": {"file": "bridge.pck"}, "farmer": 1,
    }
    assert record["official_linked"] and record["bridge_linked"]
    assert record["args"] == ["--headless"] and record["farmer_enabled"] == "1"
    preset = Path(__file__).resolve().parents[1] / "farmer" / "presets" / "one-run.json"
    assert record["config"] == json.loads(preset.read_text(encoding="utf-8")) | {
        "speed": 10.0, "max_runs": 1, "hard_exit": True, "endless": False, "display": False,
    }
    assert not record["stale_files"]
    assert not Path(record["profile"]).exists()
    assert _snapshot(profile) == before


def test_smoke_copies_packs_when_hardlinks_are_unavailable(setup_smoke, monkeypatch):
    os_, profile, records = setup_smoke
    before = _snapshot(profile)

    def cross_volume(*args):
        raise OSError(errno.EXDEV, "cross-volume hardlink")

    monkeypatch.setattr(Path, "hardlink_to", cross_volume)
    result = smoke.run_smoke(os_, profile)

    assert result.passed, result.reason
    record = json.loads((records / "attempt-1.json").read_text(encoding="utf-8"))
    assert not record["official_linked"] and not record["bridge_linked"]
    assert _snapshot(profile) == before


def test_smoke_accepts_a_falsey_failure_flag(setup_smoke, monkeypatch):
    os_, profile, _ = setup_smoke
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["falsey_failed", "falsey_failed"]')

    result = smoke.run_smoke(os_, profile)

    assert result.passed and result.attempts == 1


def test_smoke_does_not_attribute_first_log_to_retry_install_failure(setup_smoke, monkeypatch):
    os_, profile, records = setup_smoke
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["remove_candidate"]')
    monkeypatch.setenv("FAKE_SMOKE_CANDIDATE", str(patch_info.built_pack_path(os_)))

    result = smoke.run_smoke(os_, profile)

    assert result.outcome is smoke.SmokeOutcome.FAILED and result.attempts == 2
    assert "patch_farmer.pck" in result.reason and "no wins" not in result.reason
    assert {p.name for p in records.iterdir()} == {"attempt-1.json"}
    assert result.log_path is None
    assert [p.name for p in (os_.app_data_dir() / "logs").glob("smoke-*/attempt-*.log")] == ["attempt-1.log"]


@pytest.mark.parametrize(("mode", "reason"), [
    ("no_status", "no farmer_status.json"),
    ("invalid_status", "invalid farmer_status.json"),
    ("not_done", "farmer status is not done"),
    ("failed", "farmer status is failed"),
    ("no_wins", "no wins recorded"),
    ("defeat", "last run was not a victory"),
    ("no_kills", "no kills in the last run"),
    ("no_zeny", "no zeny gained in the last run"),
    ("no_finish", "missing FINISH marker"),
    ("output:SCRIPT ERROR: fake error", "script error in game output"),
    ("output:Parse Error: fake error", "script error in game output"),
    ("output:Invalid call. Fake error", "script error in game output"),
    ("output:Cannot call method. Fake error", "script error in game output"),
])
def test_each_failed_criterion_denies_smoke(setup_smoke, monkeypatch, mode, reason):
    os_, profile, records = setup_smoke
    monkeypatch.setenv("FAKE_SMOKE_MODES", json.dumps([mode, mode]))

    result = smoke.run_smoke(os_, profile)

    assert result.outcome is smoke.SmokeOutcome.FAILED
    assert not result.passed and result.reason == reason and result.attempts == 2
    assert {p.name for p in records.iterdir()} == {"attempt-1.json", "attempt-2.json"}
    assert {p.name for p in result.log_path.parent.iterdir()} == {"attempt-1.log", "attempt-2.log"}
    if mode.startswith("output:"):
        assert mode.removeprefix("output:") in result.log_path.read_text()


@pytest.mark.parametrize(("retry_mode", "reason"), [
    ("pass", "smoke passed"),
    ("defeat", "last run was not a victory"),
    ("hang", "game timed out after 2.5 s"),
])
def test_timeout_kills_tree_and_retries_with_clean_sandbox(setup_smoke, monkeypatch, retry_mode, reason):
    os_, profile, records = setup_smoke
    monkeypatch.setattr(smoke, "_TIMEOUT_SECONDS", 2.5)
    monkeypatch.setenv("FAKE_SMOKE_MODES", json.dumps(["hang", retry_mode]))
    before = _snapshot(profile)

    result = smoke.run_smoke(os_, profile)

    assert result.passed is (retry_mode == "pass") and result.attempts == 2
    assert result.reason == reason
    assert result.log_path.name == "attempt-2.log"
    assert "fake stdout" in result.log_path.with_name("attempt-1.log").read_text()
    first, second = (
        json.loads((records / f"attempt-{attempt}.json").read_text(encoding="utf-8")) for attempt in (1, 2)
    )
    assert first["profile"] != second["profile"]
    assert first["original_save"] == second["original_save"] == _ORIGINAL_SAVE
    assert not first["stale_files"] and not second["stale_files"]
    assert not Path(first["profile"]).exists() and not Path(second["profile"]).exists()
    assert (records / "grandchild.ready").exists(), "fake game did not start its child before timing out"
    assert lock_freed_within(records / "grandchild.lock", 5), "timed-out game child survived"
    assert _snapshot(profile) == before


def test_smoke_refuses_while_game_is_open(setup_smoke):
    os_, profile, records = setup_smoke
    exe = os_.game_executable()
    exe.unlink()
    if sys.platform == "win32":
        shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32" / "PING.EXE", exe)
        command = [str(exe), "-n", "60", "127.0.0.1"]
    else:
        exe.symlink_to(Path(sys.executable).resolve())
        command = [str(exe), "-c", "import time; time.sleep(60)"]
    before = _snapshot(profile)
    with platform.current().spawn_tree(command, stdout=subprocess.DEVNULL) as running:
        deadline = time.monotonic() + 10
        while running.popen.pid not in os_.game_pids():
            assert time.monotonic() < deadline, "fixture game not seen"
            time.sleep(0.05)
        result = smoke.run_smoke(os_, profile)
        assert running.popen.poll() is None

    assert result.outcome is smoke.SmokeOutcome.BUSY
    assert "close it first" in result.reason and result.attempts == 0 and result.log_path is None
    assert not list(records.iterdir())
    assert not (os_.app_data_dir() / "logs").exists()
    assert _snapshot(profile) == before


def test_smoke_honors_platform_exit_status_policy(setup_smoke, monkeypatch):
    os_, profile, _ = setup_smoke
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["bad_exit", "bad_exit"]')

    result = smoke.run_smoke(os_, profile)

    if sys.platform == "win32":
        assert result.passed and result.attempts == 1
    else:
        assert not result.passed and result.attempts == 2 and result.reason == "game exited with code 42"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux network namespace")
def test_smoke_game_runs_in_its_own_network_namespace(setup_smoke):
    os_, profile, records = setup_smoke
    unshare = shutil.which("unshare")
    if not unshare:
        pytest.skip("util-linux unshare is unavailable")
    probe = subprocess.run([unshare, "-cn", "--", "true"], capture_output=True, text=True)
    if probe.returncode:
        pytest.skip(f"no network namespace permission: {probe.stderr.strip()}")
    os_.use_real_isolation = True

    result = smoke.run_smoke(os_, profile)

    assert result.passed, result.reason
    record = json.loads((records / "attempt-1.json").read_text(encoding="utf-8"))
    assert record["netns"] != os.readlink("/proc/self/ns/net")
    assert record["interfaces"] == ["lo"]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux network namespace")
def test_smoke_fails_closed_if_network_isolation_unavailable(setup_smoke, monkeypatch, tmp_path):
    os_, profile, records = setup_smoke
    os_.use_real_isolation = True
    monkeypatch.setenv("PATH", str(tmp_path))

    result = smoke.run_smoke(os_, profile)

    assert result.outcome is smoke.SmokeOutcome.FAILED
    assert "network isolation could not start unshare" in result.reason
    assert not list(records.iterdir())
