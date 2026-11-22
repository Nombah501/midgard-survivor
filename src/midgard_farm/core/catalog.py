"""The profile catalog and the latest copy published by sandbox smoke."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..platform import Platform
from .commands import TowerKind
from .profile import ProfileNotFound, find_profile

FILENAME = "farmer_catalog.json"


@dataclass(frozen=True)
class TowerSnapshot:
    index: int
    id: str
    class_id: str
    job: str
    level: int
    xp_progress: float
    saved_at: float
    locked: bool
    farmer: bool


@dataclass(frozen=True)
class TowerCatalog:
    open: bool
    hel_unlocked: bool
    hel_reason: str
    checkpoints: tuple[int, ...]
    snapshots: tuple[TowerSnapshot, ...]

    @property
    def best_snapshot(self) -> TowerSnapshot | None:
        return max((snapshot for snapshot in self.snapshots if not snapshot.locked),
                   key=lambda snapshot: (snapshot.level, snapshot.xp_progress, snapshot.saved_at), default=None)


def _tower_snapshot(value: object) -> TowerSnapshot | None:
    if not isinstance(value, dict):
        return None
    index, level = value.get("index"), value.get("level")
    xp, saved_at = value.get("xp_progress"), value.get("saved_at")
    identity, class_id, job = value.get("id"), value.get("class"), value.get("job")
    locked, farmer = value.get("locked"), value.get("farmer")
    if (type(index) is not int or index < 0 or type(level) is not int or level < 1
            or not isinstance(xp, (int, float)) or isinstance(xp, bool) or not 0 <= xp <= 1
            or not isinstance(saved_at, (int, float)) or isinstance(saved_at, bool) or not 0 <= saved_at < 253402214400
            or not isinstance(identity, str) or not identity.strip()
            or not isinstance(class_id, str) or not class_id.strip()
            or not isinstance(job, str) or not job.strip()
            or type(locked) is not bool or type(farmer) is not bool):
        return None
    return TowerSnapshot(index, identity, class_id, job, level, xp, saved_at, locked, farmer)


def tower_catalog(latest: dict[str, Any] | None) -> TowerCatalog | None:
    """Decode optional Tower data without invalidating an older or partial catalog."""
    tower = latest.get("tower") if latest is not None else None
    if not isinstance(tower, dict):
        return None
    opened, hel = tower.get("open"), tower.get("hel_unlocked")
    reason, floors, snapshots = tower.get("hel_reason"), tower.get("checkpoints"), tower.get("snapshots")
    if (type(opened) is not bool or type(hel) is not bool or not isinstance(reason, str)
            or not isinstance(floors, list)
            or any(type(floor) is not int or floor < 1 for floor in floors)
            or floors != sorted(set(floors)) or not isinstance(snapshots, list)):
        return None
    return TowerCatalog(opened, hel, reason, tuple(floors),
                        tuple(snapshot for value in snapshots if (snapshot := _tower_snapshot(value)) is not None))


def tower_blocker(tower: TowerCatalog | None, kind: TowerKind, floor: int | None = None) -> str:
    if tower is None:
        return "Tower is unavailable in this catalog."
    if kind == "hel" and not tower.hel_unlocked:
        return tower.hel_reason or "Torre de Hel is locked."
    if not tower.open:
        return "Endless Tower is not open."
    if kind == "normal":
        if not tower.checkpoints:
            return "No Endless Tower checkpoints are available."
        if floor is not None and floor not in tower.checkpoints:
            return f"Floor {floor} is not an available Endless Tower checkpoint."
    best = tower.best_snapshot
    if best is None:
        return "No unlocked Tower snapshot is available."
    if sum(snapshot.id == best.id for snapshot in tower.snapshots) > 1:
        return "The best Tower snapshot has an ambiguous identity."
    return ""


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
