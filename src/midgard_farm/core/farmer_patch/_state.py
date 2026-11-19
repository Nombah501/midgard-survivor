import json
from pathlib import Path, PureWindowsPath
from typing import Any

from ...platform import Platform
from ..patch_info import INSTALLED_PACK

STATE = "state.json"
OFFICIAL_STATE = "official-state.json"


class PatchStateError(Exception):
    """The profile's patch state is unreadable or invalid."""


class OfficialPatchMissing(PatchStateError):
    """The official patch cannot be mounted; the game must download it."""


class GameRunning(Exception):
    """Changing the profile's patch state while the game runs is unsafe."""


def require_game_closed(os_: Platform) -> None:
    if os_.game_running():
        raise GameRunning("the game is running; close it first")


def read_state(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise PatchStateError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise PatchStateError(f"{path.name} must contain a JSON object")
    return raw, data


def patch_name(value: object) -> str:
    if (not isinstance(value, str) or not value or value in (".", "..")
            or "/" in value or PureWindowsPath(value).name != value or ":" in value):
        raise PatchStateError(f"invalid patch file name: {value!r}")
    return value


def official_name(state: dict[str, Any]) -> str:
    name = patch_name(state.get("file"))
    if name == INSTALLED_PACK:
        raise PatchStateError("expected official patch state, not the farmer patch")
    return name


def official_pack(patches: Path, state: dict[str, Any]) -> Path:
    pack = patches / official_name(state)
    if not pack.is_file():
        raise OfficialPatchMissing(f"official patch {pack.name} is missing; start the game and accept the update")
    return pack


def bridge_name(state: dict[str, Any]) -> str:
    bridge = state.get("bridge")
    name = bridge.get("file") if isinstance(bridge, dict) else None
    return patch_name(name) if name else ""


def patch_version(state: dict[str, Any]) -> str:
    version = state.get("version", "")
    if not isinstance(version, str):
        raise PatchStateError("patch version must be a string")
    return version


def snapshot_official_state(os_: Platform, profile: Path) -> None:
    """Remember the current official state before rebuilding or installing."""
    require_game_closed(os_)
    patches = profile / "patches"
    raw, state = read_state(patches / STATE)
    official_pack(patches, state)
    os_.write_atomic(patches / OFFICIAL_STATE, raw)
