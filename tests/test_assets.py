import shutil
import tomllib
from pathlib import Path

import pytest

from midgard_farm import assets
from midgard_farm.core.farmer_patch import farmer_hash

_REPO = Path(__file__).resolve().parents[1]


def test_checkout_resolves_farmer_and_project_version():
    expected = tomllib.loads((_REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert assets.farmer_inputs() == _REPO / "farmer"
    assert assets.presets_dir() == _REPO / "farmer" / "presets"
    assert assets.targets_path() == _REPO / "farmer" / "targets.json"
    assert assets.version() == expected


@pytest.mark.parametrize("frozen", [False, True], ids=["installed", "frozen"])
def test_bundled_assets_and_version_without_a_checkout(tmp_path, monkeypatch, frozen):
    package = tmp_path / "midgard_farm"
    bundled = package / "_farmer"
    checkout = _REPO / "farmer"
    for name in ("src/farmer.gd", "src/save_hook.gd", "tools/inject_hook.py", "tools/patch_player.py",
                 "presets/one-run.json", "targets.json"):
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
    assert assets.presets_dir() == bundled / "presets"
    assert assets.targets_path() == bundled / "targets.json"
    assert assets.version() == "12.34.5"
    assert farmer_hash(assets.farmer_inputs()) == farmer_hash(checkout)
