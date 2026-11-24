import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from midgard_farm import assets
from midgard_farm.core.farmer_patch import farmer_hash

_REPO = Path(__file__).resolve().parents[1]


def test_checkout_resolves_farmer_and_project_version():
    expected = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert assets.farmer_inputs() == _REPO / "farmer"
    assert assets.modes_dir() == _REPO / "farmer" / "modes"
    assert sorted(path.name for path in assets.modes_dir().glob("*.json")) == ["endless.json", "short.json"]
    assert assets.targets_path() == _REPO / "farmer" / "targets.json"
    assert assets.version() == expected


@pytest.mark.parametrize("frozen", [False, True], ids=["installed", "frozen"])
def test_bundled_assets_and_version_without_a_checkout(tmp_path, monkeypatch, frozen):
    package = tmp_path / "midgard_farm"
    bundled = package / "_farmer"
    checkout = _REPO / "farmer"
    for name in ("src/farmer.gd", "src/save_hook.gd", "tools/inject_hook.py", "tools/patch_player.py",
                 "modes/endless.json", "modes/short.json", "scenarios/one-run.json", "targets.json",
                 "obsolete_config_keys.json"):
        target = bundled / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checkout / name, target)
    metadata = tmp_path / "midgard_farm-12.34.5.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Name: midgard-farm\nVersion: 12.34.5\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(assets, "__file__", str(package / "assets.py"))
    monkeypatch.setattr("sys.frozen", frozen, raising=False)
    monkeypatch.chdir(tmp_path)

    assert assets.farmer_inputs() == bundled
    assert assets.modes_dir() == bundled / "modes"
    assert assets.targets_path() == bundled / "targets.json"
    assert assets.version() == "12.34.5"
    assert farmer_hash(assets.farmer_inputs()) == farmer_hash(checkout)


@pytest.mark.parametrize(("version", "tag", "prerelease"), [
    ("12.34.5", "v12.34.5", "false"),
    ("12.34.5rc1", "v12.34.5rc1", "true"),
    ("12.34.5.dev1", "v12.34.5.dev1", "true"),
    ("12.34.5rc1", "v12.34.5", None),
])
def test_release_tag_matches_wheel_version_and_classifies_prereleases(tmp_path, monkeypatch, version, tag, prerelease):
    # Use the installed resolver path (metadata, not the repo's pyproject).
    package = tmp_path / "midgard_farm"
    package.mkdir()
    shutil.copyfile(assets.__file__, package / "assets.py")
    (package / "__init__.py").touch()
    metadata = tmp_path / f"midgard_farm-{version}.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(f"Name: midgard-farm\nVersion: {version}\n", encoding="utf-8")
    onedir = tmp_path / "midgard-farm"
    onedir.mkdir()
    (onedir / "test-payload").touch()
    release = tmp_path / "release"
    outputs = tmp_path / "github-outputs"
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))

    result = subprocess.run([sys.executable, _REPO / "packaging" / "archive_release.py", onedir, release, tag],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)

    if prerelease is None:
        assert result.returncode != 0
        assert f"expected v{version}" in result.stderr
        assert not release.exists() and not outputs.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert len(list(release.glob("*.sha256"))) == 1
        assert f"prerelease={prerelease}" in outputs.read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(sys.platform != "linux", reason="use a symlink to stand in for a Windows short path")
def test_onedir_smoke_accepts_an_aliased_extraction_path(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(_REPO / "packaging"))
    import check_onedir

    extracted = tmp_path / "midgard farm extracted"
    onedir = extracted / "midgard-farm"
    inputs = onedir / "_internal" / "midgard_farm" / "_farmer"
    checkout = _REPO / "farmer"
    for name in ("src/farmer.gd", "src/save_hook.gd", "tools/inject_hook.py", "tools/patch_player.py",
                 "scenarios/one-run.json", "targets.json", "obsolete_config_keys.json"):
        target = inputs / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checkout / name, target)
    shutil.copytree(checkout / "modes", inputs / "modes")
    plugins = onedir / "_internal" / "PySide6" / "Qt" / "plugins" / "platforms"
    plugins.mkdir(parents=True)
    for platform in ("qoffscreen", "qwayland", "qxcb"):
        (plugins / f"lib{platform}.so").touch()
    qt = plugins.parents[1]
    libs = qt / "lib"
    libs.mkdir()
    for style in ("Basic", "Fusion"):
        impl = qt / "qml" / "QtQuick" / "Controls" / style / "impl"
        impl.mkdir(parents=True)
        (impl / "qmldir").touch()
        (impl / f"libqtquickcontrols2{style.lower()}styleimplplugin.so").touch()
        (libs / f"libQt6QuickControls2{style}StyleImpl.so.6").touch()
    (onedir / "midgard-farm-setup").touch()
    (onedir / "launcher" / "_internal").mkdir(parents=True)
    (onedir / "launcher" / "midgard-farm-launcher").touch()
    alias = tmp_path / "MIDGAR~1"
    alias.symlink_to(extracted, target_is_directory=True)

    def run_command(argv, *, cwd, **kwargs):
        if argv[-1] == "--help":
            assert argv[0] == onedir / "midgard-farm-setup"
            return subprocess.CompletedProcess(argv, 0, stdout="--uninstall")
        data = cwd / "data" / "midgard-farm"
        if argv[-1] == "--print-registration":
            assert argv == [onedir / "midgard-farm-setup", "--print-registration"]
            return subprocess.CompletedProcess(argv, 0, stdout=f'ExecStart="{data / "bin" / "midgard-farm-launcher"}"\n')
        assert argv == [data / "bin" / "midgard-farm-launcher"]
        assert argv[0].is_file() and not (data / "current").exists()
        return subprocess.CompletedProcess(argv, 1, stderr="cannot read current release pointer")

    def run_role(executable, flag, home, env):
        if flag == "--self-check":
            data = home / "data" / "midgard-farm"
            version = (data / "current").read_text(encoding="utf-8").strip()
            selected = data / "versions" / version / inputs.relative_to(onedir)
            assert executable == data / "bin" / "midgard-farm-launcher"
            return {"version": version, "inputs": str(selected),
                    "farmer_hash": farmer_hash(selected), "registration": ""}
        targets = json.loads((inputs / "targets.json").read_bytes())
        return {"version": assets.version(), "loaded": True, "messages": [],
                "mode": "endless", "route": "valhalla",
                "characters": [row["label"] for row in targets["characters"].values()]}

    monkeypatch.setattr(check_onedir.subprocess, "run", run_command)
    monkeypatch.setattr(check_onedir, "run_role", run_role)
    # The fixture's self-check has no registration; setup must provide it.
    check_onedir.check(alias / "midgard-farm")


def test_qt_filter_keeps_fusion_implementation_in_windows_toc(monkeypatch):
    monkeypatch.syspath_prepend(str(_REPO / "packaging"))
    from qt_bundle import keep_qt_file

    for destination in (
        r"PySide6\qml\QtQuick\Controls\Fusion\impl\qmldir",
        r"PySide6\qml\QtQuick\Controls\Fusion\impl\qtquickcontrols2fusionstyleimplplugin.dll",
        r"PySide6\qml\QtQuick\Controls\Basic\impl\qmldir",
        r"PySide6\qml\QtQuick\Controls\Basic\impl\qtquickcontrols2basicstyleimplplugin.dll",
        r"PySide6\Qt6QuickControls2FusionStyleImpl.dll",
        r"PySide6\Qt6QuickControls2BasicStyleImpl.dll",
    ):
        assert keep_qt_file(destination), destination
    assert not keep_qt_file(r"PySide6\qml\QtQuick\Controls\Material\impl\qmldir")
    assert not keep_qt_file(r"PySide6\Qt6WebEngineCore.dll")
