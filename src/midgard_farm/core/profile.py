"""Find the game profile by its markers, never by folder name.

The folder is `Midgard Survivors` on Linux and `Ragnarok Survivors` on
Windows, and a Game reinstall can rename it.
"""

from pathlib import Path

MARKERS = ("profile.json", "patches/state.json")


class ProfileNotFound(Exception):
    pass


def find_profile(user_data_root: Path) -> Path:
    """Return the single folder under the Godot user-data root holding every marker."""
    try:
        children = sorted(p for p in user_data_root.iterdir() if p.is_dir())
    except FileNotFoundError:
        raise ProfileNotFound(f"no Godot user-data folder at {user_data_root}; launch the game once") from None
    found = [p for p in children if all((p / m).is_file() for m in MARKERS)]
    if not found:
        raise ProfileNotFound(
            f"no folder under {user_data_root} has {' and '.join(MARKERS)}; launch the game once"
        )
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        raise ProfileNotFound(f"several profiles under {user_data_root}: {names}")
    return found[0]
