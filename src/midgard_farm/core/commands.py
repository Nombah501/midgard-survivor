"""Filesystem interface to the service: one atomically published JSON file per request."""

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..platform import Platform

Control = Literal["pause", "resume", "finish", "abort"]


@dataclass(frozen=True)
class Character:
    class_id: str
    job_path: int


@dataclass(frozen=True)
class Start:
    character: Character | None  # None leaves the preset's own selection intact.
    preset: Path

    def payload(self) -> dict:
        character = self.character
        return {"command": "start", "character": None if character is None else {
            "class": character.class_id, "job_path": character.job_path,
        }, "preset": str(self.preset.absolute())}


PatchCommand = Literal["check_again", "restore_official"]
type Command = Start | Control | PatchCommand | Literal["rollback_app"]


def decode(payload: object) -> Command:
    if not isinstance(payload, dict):
        raise ValueError("command must be a JSON object")
    match payload.get("command"):
        case "pause" | "resume" | "finish" | "abort" | "check_again" | "restore_official" | "rollback_app" as action:
            return action
        case "start":
            preset = payload.get("preset")
            if not isinstance(preset, str) or "\0" in preset or not Path(preset).is_absolute():
                raise ValueError("start needs an absolute preset path")
            character = payload.get("character")
            if "character" in payload and character is None:
                return Start(None, Path(preset))
            if not isinstance(character, dict):
                raise ValueError("start needs a character with class and job_path, or null to use the preset")
            class_id, job_path = character.get("class"), character.get("job_path")
            if (not isinstance(class_id, str) or not class_id.strip()
                    or type(job_path) is not int or job_path < 0):
                raise ValueError("character needs a class and a nonnegative integer job_path")
            return Start(Character(class_id, job_path), Path(preset))
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
    payload = command.payload() if isinstance(command, Start) else {"command": command}
    os_.write_atomic(path, json.dumps(payload).encode())
    return path
