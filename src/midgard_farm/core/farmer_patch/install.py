import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from ...platform import Platform
from .. import patch_info
from ..patch_info import INSTALLED_PACK, PatchInfoError
from ._state import (
    OFFICIAL_STATE, STATE, PatchStateError, bridge_name, official_name, official_pack,
    patch_version, read_state, require_game_closed,
)
from .gdre import sha256

_PROFILE_FILES = ("profile.json", "profile.bak.json", "profile.run", "profile.run.farmer_bak")


class InstallFailed(Exception):
    """The farmer patch could not be installed."""


def _copy_pack(source: Path, target: Path) -> None:
    with source.open("rb") as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
        dst.flush()
        os.fsync(dst.fileno())


def _install(os_: Platform, profile: Path, backups: Path) -> Path:
    require_game_closed(os_)
    patches = profile / "patches"
    state_path = patches / STATE
    official_state = patches / OFFICIAL_STATE
    installed = patches / INSTALLED_PACK
    original, state = read_state(state_path)
    was_official = state.get("file") != INSTALLED_PACK
    saved_official, official = (original, state) if was_official else read_state(official_state)
    info = patch_info.load(patch_info.info_path(os_))
    if (official_name(official), patch_version(state), bridge_name(state)) != (
        info.patch_file, info.patch_version, info.bridge_file,
    ):
        raise InstallFailed("official state changed since this farmer patch was built; rebuild it first")
    if sha256(official_pack(patches, official)) != info.patch_sha256:
        raise InstallFailed("official patch changed since this farmer patch was built; rebuild it first")
    bridge = patches / info.bridge_file
    bridge_sha = sha256(bridge) if info.bridge_file and bridge.is_file() else ""
    if bridge_sha != info.bridge_sha256:
        raise InstallFailed("official bridge changed since this farmer patch was built; rebuild it first")
    built = patch_info.built_pack_path(os_)
    if sha256(built) != info.result_sha256:
        raise InstallFailed("built farmer patch hash does not match its patch info")

    backups.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(dir=backups, prefix="install-"))
    (backup / STATE).write_bytes(original)
    for name in _PROFILE_FILES:
        if (source := profile / name).is_file():
            shutil.copyfile(source, backup / name)
    old_pack = backup / INSTALLED_PACK
    if installed.exists():
        _copy_pack(installed, old_pack)

    previous_official = official_state.read_bytes() if was_official and official_state.exists() else None
    new_state = json.dumps(state | {"file": INSTALLED_PACK, "farmer": 1}, indent=2) + "\n"
    with tempfile.TemporaryDirectory(dir=patches, prefix=".install-", ignore_cleanup_errors=True) as work:
        pending = Path(work) / INSTALLED_PACK
        _copy_pack(built, pending)
        require_game_closed(os_)
        if state_path.read_bytes() != original:
            raise InstallFailed("patch state changed while staging the farmer patch")
        pack_changed = state_changed = snapshot_changed = False
        try:
            # Mark before replacing: a durability error can follow the rename.
            pack_changed = True
            os_.replace_atomic(pending, installed)
            state_changed = True
            os_.write_atomic(state_path, new_state.encode("utf-8"))
            if sha256(installed) != info.result_sha256:
                raise InstallFailed("installed farmer patch hash does not match its patch info")
            if was_official and saved_official != previous_official:
                snapshot_changed = True
                os_.write_atomic(official_state, saved_official)
        except Exception as failure:
            rollback_errors = []
            if pack_changed:
                try:
                    if old_pack.exists():
                        _copy_pack(old_pack, pending)
                        os_.replace_atomic(pending, installed)
                    else:
                        installed.unlink(missing_ok=True)
                except OSError as exc:
                    rollback_errors.append(exc)
            for changed, path, old in (
                (state_changed, state_path, original), (snapshot_changed, official_state, previous_official),
            ):
                if changed:
                    try:
                        if old is None:
                            path.unlink(missing_ok=True)
                        elif not path.exists() or path.read_bytes() != old:
                            os_.write_atomic(path, old)
                    except OSError as exc:
                        rollback_errors.append(exc)
            if rollback_errors:
                details = "; ".join(str(error) for error in rollback_errors)
                raise InstallFailed(f"{failure}; rollback failed: {details}; backup at {backup}") from failure
            raise
    return backup


def _prune_install_backups(os_: Platform, latest: Path) -> None:
    previous = [
        backup for backup in latest.parent.glob("install-*")
        if backup != latest and not backup.is_symlink() and not backup.is_junction() and backup.is_dir()
    ]
    if not previous:
        return
    # Only active diagnostics pin backups. Historical session logs don't.
    references: list[str] = []
    for name in ("game-update.json", "quarantine.json", "state.json"):
        path = os_.app_data_dir() / name
        try:
            record = json.loads(os_.read_shared(path))
        except FileNotFoundError:
            continue
        if not isinstance(record, dict):
            raise ValueError(f"{path} is not a JSON object")
        if name == "state.json":
            record = record.get("quarantine")
        if isinstance(record, dict):
            references.extend(os.path.normcase(record[key]) for key in ("detail", "log_path")
                              if isinstance(record.get(key), str))
    for backup in previous:
        if not any(os.path.normcase(str(backup)) in text for text in references):
            try:
                shutil.rmtree(backup)
            except OSError as exc:
                print(f"farmer patch: could not prune {backup}: {exc}", file=sys.stderr)


def install(os_: Platform, profile: Path, *, backup_dir: Path | None = None) -> Path:
    """Mount the built farmer patch, retain its rollback and prune unreferenced old backups."""
    try:
        latest = _install(os_, profile, backup_dir or patch_info.farmer_dir(os_) / "backups")
    except (OSError, PatchInfoError, PatchStateError) as exc:
        raise InstallFailed(str(exc)) from exc
    try:
        _prune_install_backups(os_, latest)
    except (OSError, ValueError) as exc:
        print(f"farmer patch: could not inspect install backups: {exc}", file=sys.stderr)
    return latest


def restore(os_: Platform, profile: Path) -> None:
    """Mount the official patch again and remove the installed farmer patch."""
    require_game_closed(os_)
    patches = profile / "patches"
    state_path = patches / STATE
    current = read_state(state_path)[1] if state_path.exists() else {}
    if not current or current.get("file") == INSTALLED_PACK:
        raw, saved = read_state(patches / OFFICIAL_STATE)
        official_pack(patches, saved)
        os_.write_atomic(state_path, raw)
    else:
        # Do not downgrade a newer patch the game has already mounted.
        official_pack(patches, current)
    (patches / INSTALLED_PACK).unlink(missing_ok=True)
