import builtins
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from midgard_farm import platform
from midgard_farm.core.farmer_patch import (
    AnchorsBroken,
    BuildFailed,
    GameRunning,
    InstallFailed,
    OfficialPatchMissing,
    build,
    farmer_hash,
    install,
    restore,
    snapshot_official_state,
)
from midgard_farm.core.farmer_patch.gdre import Gdre
from midgard_farm.core.patch_info import INSTALLED_PACK, built_pack_path, farmer_dir, info_path, load
from test_profile import make_profile

REPO = Path(__file__).resolve().parents[1]
SAVE = "res://scripts/autoload/save.gdc"
PLAYER = "res://scripts/core/player.gdc"
FARMER = "res://scripts/core/farmer.gdc"
SAVE_CODE = "var _timer: = 0.0\nfunc _process(delta: float) -> void :\n\tpass\n"
PLAYER_CODE = (
    "func next_job(path: = 0) -> Dictionary:\n"
    "\tvar paths: = GameData.job_paths(class_id)\n"
    "\tvar job: Dictionary = paths[clampi(path, 0, paths.size() - 1)].duplicate()\n"
    "signal died\n"
    "func take_damage() -> void :\n"
    "\tif hp <= 0.0:\n"
    "\t\tif world.encore.siegfried_save(world, self):\n"
    "\t\t\treturn\n"
    "\t\tif effects.has(\"kaizel\"):\n"
    "\t\t\t_kaizel(world)\n"
    "\t\t\treturn\n"
    "\t\tif has_uniq and Uniques.try_ankh(world, self):\n"
    "\t\t\treturn\n"
    "\t\tif revives > 0:\n"
    "\t\t\t_revive(world)\n"
    "\t\t\treturn\n"
    "\t\tdied.emit()\n"
    "func _doom_fall(world: World, from: Enemy, what: String) -> void :\n"
    "\tif effects.has(\"kaizel\"):\n"
    "\t\t_kaizel(world)\n"
    "\t\treturn\n"
    "\tif has_uniq and Uniques.try_ankh(world, self):\n"
    "\t\treturn\n"
    "\tif revives > 0:\n"
    "\t\t_revive(world)\n"
    "\t\treturn\n"
    "\tdied.emit()\n"
    "func _revive(world: World) -> void :\n"
    "\trevives -= 1\n"
)


def write_pack(path, resources):
    path.write_text(json.dumps(resources), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def farm(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "app data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app data"))
    game = tmp_path / "Game files"
    game.mkdir()
    monkeypatch.setenv("GAME_DIR", str(game))
    os_ = platform.current()
    os_.game_executable().touch()
    # An operator's unrelated real game can be running on a development host.
    monkeypatch.setattr(os_, "game_pids", lambda: set())
    profile = make_profile(tmp_path, "Sandbox profile")
    patches = profile / "patches"
    official = patches / "patch_official.pck"
    bridge = patches / "bridge.pck"
    base = os_.game_executable().with_suffix(".pck")
    state = patches / "state.json"
    state.write_text('{ "file": "patch_official.pck", "version": "0.2.3", "base": "0.1.259", '
                     '"bridge": {"file": "bridge.pck", "version": "0.2.0"}, "other": 7 }', encoding="utf-8")
    write_pack(official, {SAVE: SAVE_CODE + "# official\n", "res://other": "untouched"})
    write_pack(bridge, {SAVE: "not the effective script"})
    write_pack(base, {PLAYER: PLAYER_CODE + "# base\n"})
    gdre = Gdre((sys.executable, str(Path(__file__).with_name("fake_gdre.py"))), "fake")
    return os_, profile, state, official, bridge, base, gdre


def test_build_uses_patch_then_bridge_then_base_and_records_inputs(farm):
    os_, profile, state, official, bridge, base, gdre = farm
    original_state = state.read_bytes()
    manifest = build(os_, profile, gdre=gdre)
    result = json.loads(built_pack_path(os_).read_text(encoding="utf-8"))

    assert result["res://other"] == "untouched"
    assert "# official" in result[SAVE] and "\t_farmer_tick()" in result[SAVE]
    assert "# base" in result[PLAYER] and 'Save.has_meta("farmer_job_paths")' in result[PLAYER]
    fall = "farmer_fell.emit(death_by, %s, revives)"
    for pierce in ("pierce", "true"):
        assert "_revive(world)\n" + ("\t" * (3 if pierce == "pierce" else 2)) + fall % pierce in result[PLAYER]
    assert result[PLAYER].count(fall % "pierce") == 5
    assert result[PLAYER].count(fall % "true") == 4
    assert result[FARMER] == (REPO / "farmer/src/farmer.gd").read_text(encoding="utf-8")
    assert manifest == load(info_path(os_))
    assert (manifest.patch_file, manifest.patch_version, manifest.patch_sha256) == (official.name, "0.2.3", digest(official))
    assert (manifest.bridge_file, manifest.bridge_sha256) == (bridge.name, digest(bridge))
    assert (manifest.bytecode, manifest.farmer_api, manifest.farmer_hash) == ("ebc36a7", 3, farmer_hash())
    assert manifest.result_sha256 == digest(built_pack_path(os_))
    assert state.read_bytes() == original_state
    assert not (state.parent / INSTALLED_PACK).exists()

    write_pack(bridge, {PLAYER: PLAYER_CODE + "# bridge\n"})
    second = build(os_, profile, gdre=gdre)
    assert second.result_sha256 != manifest.result_sha256
    assert "# bridge" in json.loads(built_pack_path(os_).read_bytes())[PLAYER]


def test_compile_receives_identical_lf_bytes_from_lf_and_crlf_injectors(farm, monkeypatch):
    os_, profile, _, _, _, _, gdre = farm
    inputs = {}
    newline = "\n"
    real_open = builtins.open
    real_run = Gdre.run
    injected = {"save_hooked.gd", "player_patched.gd"}

    def injector_open(file, mode="r", *args, **kwargs):
        if mode == "w" and isinstance(file, str) and Path(file).name in injected:
            kwargs["newline"] = newline
        return real_open(file, mode, *args, **kwargs)

    def capture_compile(self, work, *args):
        if args[0].startswith("--compile="):
            path = Path(args[0].removeprefix("--compile="))
            inputs[path.name] = path.read_bytes()
        return real_run(self, work, *args)

    monkeypatch.setattr(builtins, "open", injector_open)
    monkeypatch.setattr(Gdre, "run", capture_compile)
    lf = build(os_, profile, gdre=gdre)
    expected = inputs.copy()
    assert injected <= expected.keys()
    assert all(b"\n" in data and b"\r\n" not in data for data in expected.values())

    newline = "\r\n"
    inputs.clear()
    crlf = build(os_, profile, gdre=gdre)
    assert inputs.keys() == expected.keys()
    for name, data in inputs.items():
        assert hashlib.sha256(data).digest() == hashlib.sha256(expected[name]).digest(), name
    assert crlf.farmer_hash == lf.farmer_hash
    assert crlf.result_sha256 == lf.result_sha256


def test_decompile_cache_tracks_effective_bytes(farm, tmp_path, monkeypatch):
    os_, profile, _, official, _, _, gdre = farm
    called = tmp_path / "decompile.log"
    monkeypatch.setenv("FAKE_GDRE_DECOMPILES", str(called))
    first = build(os_, profile, gdre=gdre)
    assert build(os_, profile, gdre=gdre).result_sha256 == first.result_sha256
    write_pack(official, {SAVE: SAVE_CODE + "# different save\n"})
    build(os_, profile, gdre=gdre)
    assert called.read_text(encoding="utf-8").splitlines() == ["save.gdc", "player.gdc", "save.gdc"]


def test_farmer_hash_changes_with_each_source_but_not_checkout_line_endings(tmp_path):
    sources = tmp_path / "farmer inputs"
    inputs = ["src/farmer.gd", "src/save_hook.gd", "tools/inject_hook.py", "tools/patch_player.py"]
    for name in inputs:
        dest = sources / name
        dest.parent.mkdir(exist_ok=True, parents=True)
        shutil.copyfile(REPO / "farmer" / name, dest)
    baseline = farmer_hash()
    assert farmer_hash(sources) == baseline
    for name in inputs:
        dest = sources / name
        original = dest.read_text(encoding="utf-8")
        dest.write_text(original, encoding="utf-8", newline="\r\n")
        assert farmer_hash(sources) == baseline
        dest.write_text(original + "\n# change\n", encoding="utf-8", newline="\n")
        assert farmer_hash(sources) != baseline
        dest.write_text(original, encoding="utf-8", newline="\n")
    script = sources / inputs[0]
    script.write_text(script.read_text(encoding="utf-8").replace("API_VERSION := 3", "API_VERSION := 4"), encoding="utf-8")
    assert farmer_hash(sources) != baseline


@pytest.mark.parametrize("resource", [SAVE, PLAYER])
def test_anchor_break_is_distinct_from_other_build_failures(farm, resource):
    os_, profile, _, official, _, _, gdre = farm
    write_pack(official, {SAVE: SAVE_CODE, resource: "changed upstream"})
    with pytest.raises(AnchorsBroken, match="anchor not found"):
        build(os_, profile, gdre=gdre)
    assert not built_pack_path(os_).exists()
    assert not info_path(os_).exists()


def test_missing_or_wrong_resource_in_result_refuses_publication(farm, monkeypatch):
    os_, profile, _, _, _, _, gdre = farm
    # The original Save is present in the pack, but GDRE did not replace it.
    monkeypatch.setenv("FAKE_GDRE_DROP_RESOURCE", SAVE)
    with pytest.raises(BuildFailed, match="save.gdc"):
        build(os_, profile, gdre=gdre)
    assert not built_pack_path(os_).exists()
    assert not info_path(os_).exists()


@pytest.mark.parametrize("operation", ["build", "install"])
def test_published_patch_survives_temp_directory_cleanup_failure(farm, monkeypatch, operation):
    os_, profile, state, _, _, _, gdre = farm
    if operation == "install":
        manifest = build(os_, profile, gdre=gdre)
    rmdir = os.rmdir
    blocked = []

    def locked_work_directory(path, *args, **kwargs):
        directory = Path(path)
        if directory.parent == farmer_dir(os_) or (
            directory.parent == state.parent and directory.name.startswith(".install-")
        ):
            blocked.append(directory)
            raise PermissionError("temp directory is still held open")
        rmdir(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "rmdir", locked_work_directory)
        if operation == "build":
            manifest = build(os_, profile, gdre=gdre)
            assert load(info_path(os_)) == manifest
            assert digest(built_pack_path(os_)) == manifest.result_sha256
        else:
            snapshot = install(os_, profile)
            assert (snapshot / "state.json").is_file()
            assert json.loads(state.read_bytes())["file"] == INSTALLED_PACK
            assert digest(state.parent / INSTALLED_PACK) == manifest.result_sha256
    assert blocked


def test_sandbox_install_backs_up_profile_and_restores_exact_official_state(farm, tmp_path):
    os_, profile, state, _, _, _, gdre = farm
    original = state.read_bytes()
    profile_files = [profile / name for name in ("profile.json", "profile.bak.json", "profile.run", "profile.run.farmer_bak")]
    for item in profile_files:
        item.write_bytes(f"original {item.name}".encode())
    manifest = build(os_, profile, gdre=gdre)
    backups = tmp_path / "sandbox backups"
    snapshot = install(os_, profile, backup_dir=backups)
    installed = state.parent / INSTALLED_PACK

    assert list(backups.iterdir()) == [snapshot]
    assert (snapshot / "state.json").read_bytes() == original
    assert (state.parent / "official-state.json").read_bytes() == original
    for item in profile_files:
        assert (snapshot / item.name).read_bytes() == item.read_bytes() == f"original {item.name}".encode()
    assert not (farmer_dir(os_) / "backups").exists()
    assert json.loads(state.read_bytes()) == json.loads(original) | {"file": INSTALLED_PACK, "farmer": 1}
    assert digest(installed) == manifest.result_sha256

    # A Farmer hash change can rebuild while the old farmer patch is mounted.
    assert build(os_, profile, gdre=gdre).result_sha256 == manifest.result_sha256
    restore(os_, profile)
    assert state.read_bytes() == original
    assert not installed.exists()
    assert all(item.exists() for item in profile_files)


def test_successful_install_keeps_latest_rollback_and_active_diagnostic_backups(farm):
    os_, profile, _, _, _, _, gdre = farm
    manifest = build(os_, profile, gdre=gdre)
    backups = farmer_dir(os_) / "backups"
    journal, quarantine, state, stale, unrelated = (
        backups / name for name in ("install-journal0", "install-isolated", "install-state000", "install-stale000", "known-good")
    )
    for old in (journal, quarantine, state, stale, unrelated):
        old.mkdir(parents=True)
        (old / INSTALLED_PACK).touch()
    data = os_.app_data_dir()
    active = {
        "game-update.json": {"detail": f"install: rollback failed; backup at {journal}"},
        "quarantine.json": {"log_path": str(quarantine / "diagnostic.log")},
        "state.json": {"quarantine": {"detail": f"rollback failed; backup at {state}"}},
    }
    for name, record in active.items():
        (data / name).write_text(json.dumps(record), encoding="utf-8")

    first = install(os_, profile)
    assert set(backups.iterdir()) == {first, journal, quarantine, state, unrelated}
    for name in active:
        (data / name).unlink()
    latest = install(os_, profile)
    assert set(backups.iterdir()) == {latest, unrelated}
    assert digest(latest / INSTALLED_PACK) == manifest.result_sha256
    assert json.loads((latest / "state.json").read_bytes())["file"] == INSTALLED_PACK


def test_failed_replacement_restores_state_pack_and_official_snapshot(farm, monkeypatch):
    os_, profile, state, _, _, _, gdre = farm
    build(os_, profile, gdre=gdre)
    original = state.read_bytes()
    installed = state.parent / INSTALLED_PACK
    installed.write_bytes(b"old unmounted farmer patch")
    snapshot_official_state(os_, profile)
    replace_atomic = os_.replace_atomic
    previous = farmer_dir(os_) / "backups" / "install-previous"
    previous.mkdir(parents=True)

    def corrupt_install(src, dst):
        # Inject a failure after publication, not a fake backup or profile.
        replace_atomic(src, dst)
        if dst == installed and digest(installed) == load(info_path(os_)).result_sha256:
            installed.write_bytes(b"corrupt new farmer patch")

    monkeypatch.setattr(os_, "replace_atomic", corrupt_install)
    with pytest.raises(InstallFailed, match="installed.*hash"):
        install(os_, profile)
    assert state.read_bytes() == original
    assert installed.read_bytes() == b"old unmounted farmer patch"
    assert (state.parent / "official-state.json").read_bytes() == original
    assert previous.is_dir()


def test_stale_build_cannot_replace_a_new_official_state(farm):
    os_, profile, state, _, _, _, gdre = farm
    build(os_, profile, gdre=gdre)
    new_official = b'{"file":"new.pck","version":"0.2.4"}'
    state.write_bytes(new_official)
    with pytest.raises(InstallFailed, match="official state changed"):
        install(os_, profile)
    assert state.read_bytes() == new_official
    assert not (state.parent / INSTALLED_PACK).exists()
    assert not (farmer_dir(os_) / "backups").exists()


def test_restore_never_removes_farmer_pack_when_official_file_is_missing(farm):
    os_, profile, state, official, _, _, gdre = farm
    build(os_, profile, gdre=gdre)
    install(os_, profile)
    mounted = state.read_bytes()
    official.unlink()
    with pytest.raises(OfficialPatchMissing, match="start the game and accept the update"):
        restore(os_, profile)
    assert (state.parent / INSTALLED_PACK).is_file()
    assert state.read_bytes() == mounted


def test_install_and_restore_refuse_while_game_runs(farm, monkeypatch):
    os_, profile, state, _, _, _, gdre = farm
    build(os_, profile, gdre=gdre)
    original = state.read_bytes()
    monkeypatch.setattr(os_, "game_pids", lambda: {123})
    with pytest.raises(GameRunning):
        install(os_, profile)
    with pytest.raises(GameRunning):
        restore(os_, profile)
    assert state.read_bytes() == original
    assert not (farmer_dir(os_) / "backups").exists()
