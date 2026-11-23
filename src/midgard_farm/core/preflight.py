"""Check a launch against the discovered profile and installed farmer patch."""

import errno
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..assets import farmer_inputs
from ..platform import Platform
from . import patch_info
from .commands import MAINTENANCE_CONFIG_KEYS


_OBSOLETE_KEYS = farmer_inputs() / "obsolete_config_keys.json"
_SESSION_CONFIG_KEYS = ("stage", "danger", "class", "oaths", "wishlist", "keep_unowned_legendaries",
                        "experimental_speed", "display")


class PreflightError(Exception):
    """A restart alone will not make this launch possible (exit 78)."""


@dataclass(frozen=True)
class LaunchPlan:
    argv: list[str]
    config: bytes | None  # None means leave the existing farmer.cfg alone.


def _json_object(contents: bytes) -> dict[str, Any]:
    obj = json.loads(contents.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("expected a JSON object")
    return obj


def _read_preflight_input[T](path: Path, read: Callable[[Path], T]) -> T:
    try:
        return read(path)
    except OSError as exc:
        raise PreflightError(f"cannot read {path}: {exc.strerror or exc}") from exc


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def check_prerequisites(os_: Platform, profile: Path) -> tuple[Path, patch_info.PatchInfo]:
    """Check local prerequisites before taking locks or scanning for the game."""
    try:
        game = os_.game_executable().absolute()
    except RuntimeError as exc:
        raise PreflightError(str(exc)) from exc
    if not game.is_file() or not os.access(game, os.X_OK):
        raise PreflightError(f"game not found or not executable at {game}")

    patches = profile / "patches"
    state = patches / "state.json"
    if not state.is_file():
        raise PreflightError(f"no state.json at {state} (launch the game once)")
    try:
        info = patch_info.load(patch_info.info_path(os_))
    except patch_info.PatchInfoError as exc:
        raise PreflightError(str(exc)) from exc

    try:
        with tempfile.NamedTemporaryFile(dir=profile, prefix=".farmer-write-probe."):
            pass
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOSPC}:
            raise
        raise PreflightError(f"profile directory is not writable: {profile}") from exc
    try:
        minimum = int(os.environ.get("FARMER_MIN_FREE_MB") or "200")
    except ValueError as exc:
        raise PreflightError("FARMER_MIN_FREE_MB must be an integer") from exc
    free = shutil.disk_usage(profile).free // (1024 * 1024)
    if free < minimum:
        raise PreflightError(f"profile disk has {free} MiB free, below {minimum} MiB (FARMER_MIN_FREE_MB): {profile}")
    return game, info


def preflight(game: Path, info: patch_info.PatchInfo, profile: Path, preset: Path | None, *,
              show_game_window: bool | None = None) -> LaunchPlan:
    """Check the mounted patch and preset under the launcher lock."""
    patches = profile / "patches"
    state = patches / "state.json"

    if not isinstance(info.patch_file, str) or Path(info.patch_file).name != info.patch_file or not info.patch_file:
        raise PreflightError("farmer patch info does not name an official patch file")
    official = patches / info.patch_file
    if not official.is_file():
        raise PreflightError(f"official patch missing: {official}")
    installed = patches / patch_info.INSTALLED_PACK
    if not installed.is_file():
        raise PreflightError("farmer pack not installed")
    if _read_preflight_input(official, sha256) != info.patch_sha256:
        raise PreflightError("official patch changed (game updated); rebuild the farmer patch")
    if _read_preflight_input(installed, sha256) != info.result_sha256:
        raise PreflightError("installed farmer pack is stale; rebuild or reinstall it")
    try:
        mounted = _json_object(_read_preflight_input(state, Path.read_bytes)).get("file")
    except ValueError as exc:
        raise PreflightError(f"state.json is not a JSON object: {state}") from exc
    if mounted != patch_info.INSTALLED_PACK:
        raise PreflightError(f"state.json does not mount {patch_info.INSTALLED_PACK}; reinstall the farmer patch")

    cfg = preset if preset is not None else profile / "farmer.cfg"
    if not cfg.is_file():
        raise PreflightError(f"preset not found: {preset}" if preset else "no farmer.cfg; pass a preset or create one")
    contents = _read_preflight_input(cfg, Path.read_bytes)
    try:
        config = _json_object(contents)
    except ValueError as exc:
        raise PreflightError(f"farmer.cfg is not a JSON object: {cfg}") from exc
    obsolete = json.loads(_read_preflight_input(_OBSOLETE_KEYS, Path.read_bytes))
    removed = [key for key in obsolete if key in config]
    if preset is not None:
        removed.extend(key for key in _SESSION_CONFIG_KEYS if key in config)
        removed.extend(key for keys in MAINTENANCE_CONFIG_KEYS.values() for key in keys if key in config)
        if isinstance(builds := config.get("builds"), dict) and "class" in builds:
            removed.append("builds.class")
    if removed:
        source = f"preset {cfg}" if preset is not None else str(cfg)
        raise PreflightError(f"remove unsupported keys from {source}: {', '.join(removed)}")
    write_config = preset is not None
    if os.environ.get("FARMER_DISPLAY") in {"1", "true"}:
        show_game_window = True
    if show_game_window is not None:
        config["display"] = show_game_window
        contents = json.dumps(config, indent=2).encode()
        write_config = True

    # Other --flags make the game's updater disable all patches.
    argv = [str(game)] if config.get("display") else [str(game), "--headless"]
    return LaunchPlan(argv, contents if write_config else None)
