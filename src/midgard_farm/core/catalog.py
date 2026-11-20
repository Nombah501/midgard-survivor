"""The profile catalog and the latest copy published by sandbox smoke."""

import json
from pathlib import Path
from typing import Any

from ..platform import Platform
from .profile import ProfileNotFound, find_profile

FILENAME = "farmer_catalog.json"


def _decode(raw: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or type(data.get("schema")) is not int or data["schema"] != 1:
        return None
    stamp = data.get("written_at")
    # Positive Unix seconds in the datetime range; also rules out NaN/infinity.
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not 0 < stamp < 253402214400:
        return None
    if not all(type(data.get(key)) is int for key in ("max_difficulty", "unlocked_max_difficulty")):
        return None
    if not all(isinstance(data.get(key), list) for key in ("locations", "oaths", "legendaries", "owned_item_ids")):
        return None
    return data


def read_catalog(os_: Platform, directory: Path) -> dict[str, Any] | None:
    """Read a supported catalog from one directory, if available."""
    try:
        return _decode(os_.read_shared(directory / FILENAME))
    except OSError:
        return None


def read_latest(os_: Platform) -> dict[str, Any] | None:
    """Choose by the game's write time, preferring the profile in a tie."""
    published = read_catalog(os_, os_.app_data_dir())
    try:
        profile = find_profile(os_.godot_user_data_root())
    except (OSError, ProfileNotFound):
        return published
    live = read_catalog(os_, profile)
    if live is not None and (published is None or live["written_at"] >= published["written_at"]):
        return live
    return published


def publish(os_: Platform, sandbox: Path, app_dir: Path) -> bool:
    """Publish a valid catalog verbatim while its smoke sandbox still exists."""
    try:
        raw = os_.read_shared(sandbox / FILENAME)
    except FileNotFoundError:
        return False
    if _decode(raw) is None:
        return False
    os_.write_atomic(app_dir / FILENAME, raw)
    return True
