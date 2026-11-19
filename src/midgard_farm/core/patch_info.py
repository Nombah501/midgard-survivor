"""The farmer patch info: what a built farmer patch was made from.

Written by the build (farmer patch build/install), read by preflight and the
Game update states. JSON; new fields only, so an older app can still read it.
"""

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

from ..platform import Platform

# The farmer patch's file name inside the profile's `patches/` folder.
INSTALLED_PACK = "patch_farmer.pck"


@dataclass(frozen=True)
class PatchInfo:
    patch_file: str  # official patch file name in `patches/`, e.g. patch_0.2.3.pck
    patch_version: str
    patch_sha256: str
    bridge_file: str
    bridge_sha256: str
    bytecode: str  # GDRE bytecode revision, e.g. ebc36a7
    farmer_api: int
    farmer_hash: str  # Farmer hash of the build inputs
    result_sha256: str  # sha256 of the built patch_farmer.pck
    built_at: str  # ISO 8601 UTC


class PatchInfoError(Exception):
    """The patch info is missing or unreadable: no usable farmer patch build."""


def farmer_dir(os_: Platform) -> Path:
    """Where the app keeps the built farmer patch and its info."""
    return os_.app_data_dir() / "farmer"


def built_pack_path(os_: Platform) -> Path:
    return farmer_dir(os_) / INSTALLED_PACK


def info_path(os_: Platform) -> Path:
    return farmer_dir(os_) / "patch_farmer.json"


def load(path: Path) -> PatchInfo:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PatchInfoError(f"no farmer patch info at {path}") from None
    except (OSError, ValueError) as exc:
        raise PatchInfoError(f"unreadable farmer patch info {path}: {exc}") from None
    names = {f.name for f in dataclasses.fields(PatchInfo)}
    if not isinstance(data, dict) or not names <= data.keys():
        raise PatchInfoError(f"incomplete farmer patch info {path}")
    return PatchInfo(**{k: data[k] for k in names})


def save(os_: Platform, path: Path, info: PatchInfo) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os_.write_atomic(path, (json.dumps(dataclasses.asdict(info), indent=2) + "\n").encode())
