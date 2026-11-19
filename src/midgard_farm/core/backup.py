"""Routine profile snapshots and atomic publication of verified Known-good backups."""

import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from ..platform import Platform
from .preflight import sha256

PROFILE_FILES = ("profile.json", "profile.bak.json", "profile.run", "profile.run.farmer_bak")
_ROUTINE_NAME = re.compile(r"[0-9]{8}-[0-9]{6}-[0-9]+")
_GENERATION_NAME = re.compile(r"snapshot-[0-9a-f]{32}")


def backup_directory(os_: Platform) -> Path:
    return Path(os.environ.get("FARMER_BACKUP_DIR") or os_.app_data_dir() / "backups")


def snapshot_profile(profile: Path, backups: Path) -> None:
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}{time.time_ns()}"
    snapshot = backups / name
    snapshot.mkdir(parents=True)
    for name in PROFILE_FILES:
        if (profile / name).is_file():
            shutil.copyfile(profile / name, snapshot / name)

    routine = [p for p in backups.iterdir() if _ROUTINE_NAME.fullmatch(p.name) and p.is_dir()]
    routine.sort(key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    for old in routine[10:]:
        shutil.rmtree(old, ignore_errors=True)


def known_good_snapshot(backups: Path) -> Path | None:
    """Resolve the published generation; hold the service lock while using it."""
    directory = backups / "known-good"
    try:
        generation = (directory / "current").read_text(encoding="ascii")
    except FileNotFoundError:
        return None
    if not _GENERATION_NAME.fullmatch(generation) or not (directory / generation).is_dir():
        raise OSError(f"invalid Known-good backup pointer: {directory / 'current'}")
    return directory / generation


def publish_known_good(os_: Platform, profile: Path, backups: Path) -> None:
    files = [PROFILE_FILES[0], *(name for name in PROFILE_FILES[1:] if (profile / name).exists())]
    hashes = {}
    for name in files:
        path = profile / name
        if not path.is_file() or not path.stat().st_size:
            raise OSError(f"missing or empty profile file: {path}")
        hashes[name] = sha256(path)

    backups.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=backups, prefix=".known-good.") as staging:
        candidate = Path(staging) / "snapshot"
        restored = Path(staging) / "user"
        candidate.mkdir()
        restored.mkdir()
        for name, digest in hashes.items():
            shutil.copyfile(profile / name, candidate / name)
            shutil.copyfile(candidate / name, restored / name)
            if sha256(restored / name) != digest:
                raise OSError(f"restored copy of {name} does not match the source")
        (candidate / "SHA256SUMS").write_bytes(
            "".join(f"{digest}  {name}\n" for name, digest in hashes.items()).encode("ascii")
        )

        directory = backups / "known-good"
        directory.mkdir(exist_ok=True)
        generation = f"snapshot-{uuid.uuid4().hex}"
        candidate.rename(directory / generation)
        os_.write_atomic(directory / "current", generation.encode("ascii"))

    for old in directory.iterdir():
        if old.name != generation and _GENERATION_NAME.fullmatch(old.name):
            shutil.rmtree(old, ignore_errors=True)
