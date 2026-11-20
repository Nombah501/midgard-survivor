"""Filesystem interface to the service: one atomically published JSON file per request."""

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from ..platform import Platform

Control = Literal["pause", "resume", "finish", "abort"]

MAINTENANCE_CONFIG_KEYS = {
    "upgrades": ("auto_upgrades", "auto_sage"),
    "card_fusion": ("auto_fuse",),
    "star_smith": ("auto_potential",),
    "storage_cleanup": ("auto_storage_prune",),
}


@dataclass(frozen=True)
class Character:
    class_id: str
    job_path: int


@dataclass(frozen=True)
class SessionSettings:
    location: str | None = None
    difficulty: int | None = None
    oaths: dict[str, int] = field(default_factory=dict)
    wishlist: list[str] = field(default_factory=list)
    upgrades: bool = True
    card_fusion: bool = True
    star_smith: bool = False
    storage_cleanup: bool = False

    @classmethod
    def decode(cls, value: object) -> "SessionSettings":
        if (not isinstance(value, dict) or not {"location", "difficulty"} <= value.keys()
                or value.keys() - {"location", "difficulty", "oaths", "wishlist", *MAINTENANCE_CONFIG_KEYS}):
            raise ValueError(
                "settings must be an object with location, difficulty and optional oaths, wishlist and maintenance switches"
            )
        location, difficulty = value["location"], value["difficulty"]
        if location is not None and (not isinstance(location, str) or not location.strip() or "\0" in location):
            raise ValueError("settings.location must be a location id or null for Automatic")
        if difficulty is not None and type(difficulty) is not int:
            raise ValueError("settings.difficulty must be an integer or null for Automatic")
        oaths = value.get("oaths", {})
        if not isinstance(oaths, dict) or any(
            not isinstance(oath, str) or not oath.strip() or "\0" in oath or type(rank) is not int or rank <= 0
            for oath, rank in oaths.items()
        ):
            raise ValueError("settings.oaths must map oath ids to positive integer ranks")
        wishlist = value.get("wishlist", [])
        if (not isinstance(wishlist, list)
                or any(not isinstance(item, str) or not item.strip() or "\0" in item for item in wishlist)
                or len(set(wishlist)) != len(wishlist)):
            raise ValueError("settings.wishlist must be an array of distinct item ids")
        maintenance = {}
        for name in MAINTENANCE_CONFIG_KEYS:
            enabled = value.get(name, getattr(cls, name))
            if not isinstance(enabled, bool):
                raise ValueError(f"settings.{name} must be a boolean")
            maintenance[name] = enabled
        return cls(location, difficulty, oaths, wishlist, **maintenance)

    def maintenance(self) -> dict[str, bool]:
        return {name: getattr(self, name) for name in MAINTENANCE_CONFIG_KEYS}

    def config(self) -> dict:
        switches = {key: enabled for name, enabled in self.maintenance().items() for key in MAINTENANCE_CONFIG_KEYS[name]}
        return {"stage": self.location or "", "danger": "auto" if self.difficulty is None else self.difficulty,
                "oaths": self.oaths, "wishlist": self.wishlist, **switches}


@dataclass(frozen=True)
class Start:
    character: Character | None  # Legacy clients may leave character selection to the farmer.
    preset: Path
    settings: SessionSettings = field(default_factory=SessionSettings)

    def payload(self) -> dict:
        character = self.character
        return {"command": "start", "character": None if character is None else {
            "class": character.class_id, "job_path": character.job_path,
        }, "preset": str(self.preset.absolute()), "settings": asdict(self.settings)}


@dataclass(frozen=True)
class Resume:
    settings: SessionSettings

    def payload(self) -> dict:
        return {"command": "resume", "settings": asdict(self.settings)}


PatchCommand = Literal["check_again", "restore_official"]
type Command = Start | Resume | Control | PatchCommand | Literal["rollback_app"]


def decode(payload: object) -> Command:
    if not isinstance(payload, dict):
        raise ValueError("command must be a JSON object")
    match payload.get("command"):
        case "resume":
            return Resume(SessionSettings.decode(payload["settings"])) if "settings" in payload else "resume"
        case "pause" | "finish" | "abort" | "check_again" | "restore_official" | "rollback_app" as action:
            return action
        case "start":
            preset = payload.get("preset")
            if not isinstance(preset, str) or "\0" in preset or not Path(preset).is_absolute():
                raise ValueError("start needs an absolute preset path")
            character = payload.get("character")
            settings = SessionSettings.decode(payload["settings"]) if "settings" in payload else SessionSettings()
            if "character" in payload and character is None:
                return Start(None, Path(preset), settings)
            if not isinstance(character, dict):
                raise ValueError("start needs a character with class and job_path")
            class_id, job_path = character.get("class"), character.get("job_path")
            if (not isinstance(class_id, str) or not class_id.strip()
                    or type(job_path) is not int or job_path < 0):
                raise ValueError("character needs a class and a nonnegative integer job_path")
            return Start(Character(class_id, job_path), Path(preset), settings)
        case _:
            raise ValueError("unknown service command")


def directory(os_: Platform) -> Path:
    return os_.app_data_dir() / "commands"


def rejection_path(os_: Platform, request: Path) -> Path:
    return os_.app_data_dir() / "command-rejections" / request.name


def submit(os_: Platform, command: Command) -> Path:
    """Publish a request and return its path for looking up a refusal."""
    queue = directory(os_)
    queue.mkdir(parents=True, exist_ok=True)
    path = queue / f"{time.time_ns():020d}-{uuid.uuid4().hex}.json"
    payload = command.payload() if isinstance(command, (Start, Resume)) else {"command": command}
    os_.write_atomic(path, json.dumps(payload).encode())
    return path
