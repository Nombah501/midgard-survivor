"""Drive the Game update module with real profile files and fake game tools."""

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from midgard_farm import platform
from midgard_farm.core import game_update, patch_info
from midgard_farm.core.farmer_patch import farmer_hash
from midgard_farm.core.farmer_patch.gdre import Gdre
from midgard_farm.core.preflight import PreflightError
from test_profile import godot_root, make_profile


TOOLS = Path(__file__).with_name("fake_update_tools.py")
SAVE = "res://scripts/autoload/save.gdc"
PLAYER = "res://scripts/core/player.gdc"
SAVE_CODE = "var _timer: = 0.0\nfunc _process(delta: float) -> void :\n\tpass\n"
PLAYER_CODE = (
    "func next_job(path: = 0) -> Dictionary:\n"
    "\tvar paths: = GameData.job_paths(class_id)\n"
    "\tvar job: Dictionary = paths[clampi(path, 0, paths.size() - 1)].duplicate()\n"
)


class UpdateGamePlatform(type(platform.current())):
    game_exe_name = "midgard-update-fixture.exe" if sys.platform == "win32" else "midgard-update-fixture"

    def __init__(self, running):
        self.running = running

    def game_pids(self):
        return {1} if self.running.exists() else set()

    def spawn_tree(self, argv, *, isolate_network=False, **kwargs):
        assert isolate_network and argv[0] == str(self.game_executable())
        return super().spawn_tree([sys.executable, str(TOOLS), "smoke", *argv[1:]], **kwargs)


class Events:
    def __init__(self):
        self.states = []
        self.records = []
        self.notifications = []

    def state(self, kind, reason):
        self.states.append((kind, reason))

    def history(self, event):
        self.records.append(event)

    def notify(self, event, message):
        self.notifications.append((event, message))


class UpdateFarm:
    def __init__(self, tmp_path, profile, monkeypatch):
        self.profile = profile
        self.patches = profile / "patches"
        self.running = tmp_path / "fake game running"
        self.trace = tmp_path / "trace.jsonl"
        self.records = tmp_path / "smoke records"
        self.records.mkdir()
        self.os = UpdateGamePlatform(self.running)
        tmp_game = tmp_path / "game files"
        tmp_game.mkdir()
        monkeypatch.setenv("GAME_DIR", str(tmp_game))
        fake_exe = self.os.game_executable()
        fake_exe.touch()
        fake_exe.chmod(0o755)
        monkeypatch.setenv("FAKE_SMOKE_PROFILE", str(profile))
        monkeypatch.setenv("FAKE_SMOKE_RECORDS", str(self.records))
        monkeypatch.setenv("FAKE_UPDATE_TRACE", str(self.trace))
        monkeypatch.setenv("FAKE_UPDATE_RUNNING", str(self.running))
        self.events = Events()
        self.gdre = Gdre((sys.executable, str(TOOLS), "gdre"), "fake-update")
        (self.patches / "bridge.pck").write_text("fake bridge", encoding="utf-8")
        (profile / "profile.json").write_text('{"zeny":100}', encoding="utf-8")
        (profile / "profile.run").write_bytes(b"run save")
        self.publish_official()

    def pipeline(self, **kwargs):
        return game_update.GameUpdatePipeline(self.os, self.profile, self.events, gdre=self.gdre, **kwargs)

    def publish_official(self, *, version="2", save_code=SAVE_CODE):
        state = {"file": "official.pck", "version": version, "base": "1", "bridge": {"file": "bridge.pck"}}
        write_state(self.profile, state)
        (self.patches / "official.pck").write_text(
            json.dumps({SAVE: save_code, PLAYER: PLAYER_CODE, "version": version}), encoding="utf-8",
        )
        (self.patches / patch_info.INSTALLED_PACK).unlink(missing_ok=True)
        return state

    def observations(self):
        return [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()] \
            if self.trace.exists() else []


@pytest.fixture
def farm(tmp_path, update_profile, monkeypatch):
    return UpdateFarm(tmp_path, update_profile[1], monkeypatch)


@pytest.fixture
def update_profile(tmp_path, monkeypatch):
    home = tmp_path / "temporary Godot data"
    for name in ("XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(home))
    os_ = platform.current()
    profile = make_profile(godot_root(home), "Renamed Game Profile")
    return os_, profile


def official_state(profile, *, version="2"):
    return {"file": f"patch_{version}.pck", "version": version, "base": "1", "bridge": {"file": "bridge.pck"}}


def write_state(profile, state, name="state.json"):
    (profile / "patches" / name).write_bytes((json.dumps(state) + "\n").encode())


def save_info(os_, *, version="2", fingerprint=None):
    info = patch_info.PatchInfo(
        patch_file=f"patch_{version}.pck", patch_version=version, patch_sha256="official digest",
        bridge_file="bridge.pck", bridge_sha256="bridge digest", bytecode="ebc36a7", farmer_api=3,
        farmer_hash=fingerprint if fingerprint is not None else farmer_hash(),
        result_sha256="candidate digest", built_at="2026-01-01T00:00:00Z",
    )
    patch_info.save(os_, patch_info.info_path(os_), info)
    return info


@pytest.mark.parametrize("mounted,known_version,fingerprint,expected", [
    (True, "2", None, "current"),
    (False, "1", None, "game_update"),
    (False, "2", None, "farmer_removed_or_stale"),
    (True, "2", "old farmer", "farmer_removed_or_stale"),
    (False, None, None, "game_update"),
])
def test_classifies_by_metadata_without_reading_game_packs(update_profile, mounted, known_version,
                                                            fingerprint, expected):
    os_, profile = update_profile
    state = official_state(profile)
    if mounted:
        write_state(profile, state, "official-state.json")
        (profile / "patches" / patch_info.INSTALLED_PACK).touch()
        state = state | {"file": patch_info.INSTALLED_PACK, "farmer": 1}
    write_state(profile, state)
    if known_version is not None:
        save_info(os_, version=known_version, fingerprint=fingerprint)
    # Neither the official pack nor the bridge exists: only their metadata is needed.
    assert game_update.classify(os_, profile).value == expected


@pytest.mark.parametrize("content", [None, b"", b" \n", b"{}"])
def test_missing_or_empty_state_is_game_reinstall(update_profile, content):
    os_, profile = update_profile
    state = profile / "patches/state.json"
    if content is None:
        state.unlink()
    else:
        state.write_bytes(content)
    assert game_update.classify(os_, profile) is game_update.GameUpdateState.GAME_REINSTALL


@pytest.mark.parametrize("content", [b"[", b"null", b'{"file": "../pack.pck"}'])
def test_nonempty_invalid_state_remains_a_preflight_error(update_profile, content):
    os_, profile = update_profile
    (profile / "patches/state.json").write_bytes(content)
    with pytest.raises(PreflightError):
        game_update.classify(os_, profile)


def test_game_update_refreshes_then_builds_then_smokes_before_real_install(farm):
    before = farm.patches.joinpath("state.json").read_text(encoding="utf-8")
    profile_before = farm.profile.joinpath("profile.json").read_bytes()

    assert isinstance(farm.pipeline().run(), game_update.Ready)

    assert farm.observations() == [
        {"stage": "build", "state": before, "snapshot": before},
        {"stage": "smoke", "state": before, "snapshot": before},
    ]
    result = json.loads(farm.patches.joinpath("state.json").read_bytes())
    assert result == json.loads(before) | {"file": "patch_farmer.pck", "farmer": 1}
    info = patch_info.load(patch_info.info_path(farm.os))
    assert hashlib.sha256(farm.patches.joinpath("patch_farmer.pck").read_bytes()).hexdigest() == info.result_sha256
    assert farm.profile.joinpath("profile.json").read_bytes() == profile_before
    assert farm.events.records == [{
        "kind": "game_update", "classification": "game_update", "outcome": "ready",
        "official_patch_sha256": info.patch_sha256, "farmer_hash": info.farmer_hash,
    }]
    assert [event for event, _ in farm.events.notifications] == ["game_update_handled"]
    assert farm.events.states[-1] == ("ready", None)


def snapshot(profile):
    return {path.relative_to(profile).as_posix(): path.read_bytes() for path in profile.rglob("*") if path.is_file()}


@pytest.mark.parametrize("failure", ["build_failed", "anchors_broken", "smoke_failed"])
def test_failure_leaves_official_mounted_and_profile_saves_untouched(farm, monkeypatch, failure):
    if failure == "anchors_broken":
        farm.publish_official(save_code="upstream changed the injector anchor\n")
    elif failure == "build_failed":
        monkeypatch.setenv("FAKE_GDRE_DROP_RESOURCE", SAVE)
    else:
        monkeypatch.setenv("FAKE_SMOKE_MODES", '["failed", "no_wins"]')
    before = snapshot(farm.profile)

    result = farm.pipeline().run()

    assert isinstance(result, game_update.Quarantine)
    assert result.reason == failure and result.log_path.is_file()
    assert result.detail and "\n" not in result.detail
    assert snapshot(farm.profile) == before | {"patches/official-state.json": before["patches/state.json"]}
    assert [event for event, _ in farm.events.notifications] == [failure]
    assert len(farm.events.records) == 1
    assert farm.events.records[0] | {
        "outcome": "quarantine", "reason": failure, "detail": result.detail, "log_path": str(result.log_path),
    } == farm.events.records[0]
    stages = [record["stage"] for record in farm.observations()]
    assert stages == (["build", "smoke", "smoke"] if failure == "smoke_failed" else ["build"])


def farmer_sources(target):
    root = Path(__file__).resolve().parents[1] / "farmer"
    for name in ("src/farmer.gd", "src/save_hook.gd", "tools/inject_hook.py", "tools/patch_player.py"):
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, path)
    return target / "src/farmer.gd"


@pytest.mark.parametrize("lift", ["check_again", "game_update", "farmer_hash_change"])
def test_retry_block_persists_and_only_lifts_for_new_inputs_or_check_again(farm, tmp_path, monkeypatch, lift):
    sources = tmp_path / "farmer sources"
    farmer_script = farmer_sources(sources)
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["failed", "failed", "pass"]')
    result = farm.pipeline(sources=sources).run()
    assert isinstance(result, game_update.Quarantine) and result.reason == "smoke_failed"
    failed_trace = farm.observations()
    old_log = result.log_path.read_bytes()

    blocked = farm.pipeline(sources=sources).run()
    assert isinstance(blocked, game_update.Blocked) and blocked.reason == "smoke_failed"
    assert (blocked.detail, blocked.log_path) == (result.detail, result.log_path)
    assert farm.observations() == failed_trace
    assert result.log_path.read_bytes() == old_log
    assert len(farm.events.records) == len(farm.events.notifications) == 1

    if lift == "game_update":
        # The updater may replace bytes even when state.json uses the same identity.
        farm.publish_official(save_code=SAVE_CODE + "# new official code\n")
    elif lift == "farmer_hash_change":
        with farmer_script.open("a", encoding="utf-8") as stream:
            stream.write("\n# new farmer build\n")
    assert isinstance(farm.pipeline(sources=sources).run(check_again=(lift == "check_again")), game_update.Ready)
    assert [entry["stage"] for entry in farm.observations()[len(failed_trace):]] == ["build", "smoke"]


def test_check_again_while_busy_rearms_the_persisted_block(farm, monkeypatch):
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["failed", "failed", "pass"]')
    assert isinstance(farm.pipeline().run(), game_update.Quarantine)
    farm.running.touch()
    assert farm.pipeline().run(check_again=True) == game_update.Wait("waiting for the game to close")
    farm.running.unlink()

    assert isinstance(farm.pipeline().run(), game_update.Ready)
    assert [entry["stage"] for entry in farm.observations()] == ["build", "smoke", "smoke", "build", "smoke"]


@pytest.mark.parametrize("fail", [False, True])
def test_mounted_farmer_hash_change_keeps_official_snapshot(farm, tmp_path, monkeypatch, fail):
    assert isinstance(farm.pipeline().run(), game_update.Ready)
    official = farm.patches / "official-state.json"
    official.write_bytes(official.read_bytes().replace(b"\n", b"\r\n"))
    before = snapshot(farm.profile)
    sources = tmp_path / "farmer sources"
    farmer_script = farmer_sources(sources)
    with farmer_script.open("a", encoding="utf-8") as stream:
        stream.write("\n# new farmer build\n")
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["pass", "failed", "failed"]' if fail else '["pass", "pass"]')

    result = farm.pipeline(sources=sources).run()

    after = snapshot(farm.profile)
    saved = before["patches/official-state.json"]
    assert after["patches/official-state.json"] == saved
    assert after["profile.json"] == before["profile.json"] and after["profile.run"] == before["profile.run"]
    for observation in farm.observations()[2:]:
        assert observation["snapshot"].encode() == saved
        assert json.loads(observation["state"])["file"] == "patch_farmer.pck"
    if fail:
        assert isinstance(result, game_update.Quarantine) and result.reason == "smoke_failed"
        del before["patches/patch_farmer.pck"]
        assert after == before | {"patches/state.json": saved}
    else:
        assert isinstance(result, game_update.Ready)
        assert after["patches/patch_farmer.pck"] != before["patches/patch_farmer.pck"]


def test_failed_mounted_rebuild_restores_official_only_after_game_closes(farm, tmp_path, monkeypatch):
    assert isinstance(farm.pipeline().run(), game_update.Ready)
    official = farm.patches / "official-state.json"
    official.write_bytes(official.read_bytes().replace(b"\n", b"\r\n"))
    before = snapshot(farm.profile)
    sources = tmp_path / "changed sources"
    script = farmer_sources(sources)
    with script.open("a", encoding="utf-8") as out:
        out.write("\n# new farmer build\n")
    monkeypatch.setenv("FAKE_GDRE_DROP_RESOURCE", SAVE)
    monkeypatch.setenv("FAKE_UPDATE_REOPEN", "build")
    pipeline = farm.pipeline(sources=sources, close_grace_seconds=0)
    assert pipeline.run() == game_update.Wait("waiting for the game to close")
    assert snapshot(farm.profile) == before

    farm.running.unlink()
    result = pipeline.run()
    assert isinstance(result, game_update.Quarantine) and result.reason == "build_failed"
    del before["patches/patch_farmer.pck"]
    assert snapshot(farm.profile) == before | {"patches/state.json": before["patches/official-state.json"]}
    assert [item["stage"] for item in farm.observations()] == ["build", "smoke", "build"]


def test_removed_farmer_patch_reinstalls_existing_pack_without_build_or_smoke(farm):
    assert isinstance(farm.pipeline().run(unattended=False), game_update.Ready)
    previous = farm.observations()
    pack = farm.patches / "patch_farmer.pck"
    content = pack.read_bytes()
    pack.unlink()
    (farm.patches / "state.json").write_bytes((farm.patches / "official-state.json").read_bytes())

    assert isinstance(farm.pipeline().run(), game_update.Ready)

    assert pack.read_bytes() == content
    assert farm.observations() == previous
    assert [entry["classification"] for entry in farm.events.records] == ["game_update", "farmer_removed_or_stale"]
    assert not farm.events.notifications


def test_removed_farmer_patch_rebuilds_when_cached_pack_no_longer_matches_info(farm, monkeypatch):
    monkeypatch.setenv("FAKE_SMOKE_MODES", '["pass", "pass"]')
    assert isinstance(farm.pipeline().run(), game_update.Ready)
    previous = farm.observations()
    original = patch_info.built_pack_path(farm.os).read_bytes()
    farm.publish_official()
    patch_info.built_pack_path(farm.os).write_bytes(b"corrupted candidate")

    assert isinstance(farm.pipeline().run(), game_update.Ready)
    assert (farm.patches / "patch_farmer.pck").read_bytes() == original
    assert [entry["stage"] for entry in farm.observations()[len(previous):]] == ["build", "smoke"]


def test_game_reinstall_has_no_automatic_side_effects(farm):
    (farm.patches / "state.json").unlink()
    before = snapshot(farm.profile)
    pipeline = farm.pipeline()
    for _ in range(2):
        assert pipeline.run() == game_update.Blocked("start the game and accept the update")
    assert snapshot(farm.profile) == before
    assert not farm.observations() and not farm.events.notifications
    assert len(farm.events.records) == 1
    assert farm.events.records[0]["classification"] == "game_reinstall"


def test_game_running_then_grace_delays_all_update_work(farm):
    farm.running.touch()
    pipeline = farm.pipeline(close_grace_seconds=0.05)
    before = snapshot(farm.profile)
    assert pipeline.run() == game_update.Wait("waiting for the game to close")
    farm.running.unlink()
    assert pipeline.run() == game_update.Wait("waiting for the game to close")
    assert snapshot(farm.profile) == before and not farm.observations()
    time.sleep(0.06)
    assert isinstance(pipeline.run(), game_update.Ready)


@pytest.mark.parametrize("busy_stage", ["build", "smoke"])
def test_game_reopening_at_smoke_or_install_waits_and_resumes_without_rebuilding(farm, monkeypatch, busy_stage):
    monkeypatch.setenv("FAKE_UPDATE_REOPEN", busy_stage)
    pipeline = farm.pipeline(close_grace_seconds=0)
    original = (farm.patches / "state.json").read_bytes()

    assert pipeline.run() == game_update.Wait("waiting for the game to close")
    assert (farm.patches / "state.json").read_bytes() == original
    assert not (farm.patches / "patch_farmer.pck").exists()
    assert not farm.events.records and not farm.events.notifications
    assert [entry["stage"] for entry in farm.observations()] == (
        ["build"] if busy_stage == "build" else ["build", "smoke"]
    )

    farm.running.unlink()
    monkeypatch.delenv("FAKE_UPDATE_REOPEN")
    assert isinstance(farm.pipeline(close_grace_seconds=0).run(), game_update.Ready)
    assert [entry["stage"] for entry in farm.observations()] == ["build", "smoke"]


def test_current_farmer_patch_is_a_no_op(farm):
    pipeline = farm.pipeline()
    assert isinstance(pipeline.run(), game_update.Ready)
    before = snapshot(farm.profile)
    observed = farm.observations()

    assert isinstance(pipeline.run(), game_update.Ready)
    assert snapshot(farm.profile) == before and farm.observations() == observed
    assert len(farm.events.records) == len(farm.events.notifications) == 1


def test_missing_game_is_a_legacy_preflight_error(farm):
    farm.os.game_executable().unlink()
    before = snapshot(farm.profile)
    with pytest.raises(PreflightError, match="game not found"):
        farm.pipeline().run()
    assert snapshot(farm.profile) == before and not farm.observations()
    assert not farm.events.records and not farm.events.notifications
