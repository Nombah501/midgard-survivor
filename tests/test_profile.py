import sys
from pathlib import Path

import pytest

from midgard_farm.core.profile import ProfileNotFound, find_profile


def make_profile(root: Path, name: str) -> Path:
    profile = root / name
    (profile / "patches").mkdir(parents=True)
    (profile / "profile.json").write_text("{}")
    (profile / "patches" / "state.json").write_text("{}")
    return profile


def godot_root(home: Path) -> Path:
    """Godot's user:// root: $XDG_DATA_HOME/godot/app_userdata on Linux,
    %APPDATA%\\Godot\\app_userdata on Windows."""
    return home / ("Godot" if sys.platform == "win32" else "godot") / "app_userdata"


def test_finds_profile_by_markers_in_folder_with_space(tmp_path):
    (tmp_path / "Godot RE Tools").mkdir()
    (tmp_path / "half" / "patches").mkdir(parents=True)
    (tmp_path / "half" / "profile.json").write_text("{}")  # no state.json
    profile = make_profile(tmp_path, "Ragnarok Survivors")

    assert find_profile(tmp_path) == profile


def test_missing_root_or_markers_is_not_found(tmp_path):
    with pytest.raises(ProfileNotFound):
        find_profile(tmp_path / "absent")
    (tmp_path / "Midgard Survivors").mkdir()
    with pytest.raises(ProfileNotFound):
        find_profile(tmp_path)


def test_two_candidate_profiles_are_refused_not_guessed(tmp_path):
    make_profile(tmp_path, "Midgard Survivors")
    make_profile(tmp_path, "Ragnarok Survivors")

    with pytest.raises(ProfileNotFound, match="Midgard Survivors.*Ragnarok Survivors"):
        find_profile(tmp_path)
