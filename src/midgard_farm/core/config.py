"""Service configuration, edited by the operator in app data."""

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..platform import Platform


@dataclass(frozen=True)
class Config:
    ntfy_url: str = ""
    game_dir: Path | None = None


def config_path(os_: Platform) -> Path:
    return os_.app_data_dir() / "config.json"


def read_config(os_: Platform) -> Config:
    try:
        payload = json.loads(os_.read_shared(config_path(os_)))
        if not isinstance(payload, dict):
            raise ValueError
    except FileNotFoundError:
        return Config()
    except (OSError, ValueError):
        print("supervisor: invalid or unreadable config.json; ignoring it", flush=True)
        return Config()

    try:
        url = _ntfy_url(payload.get("ntfy_url", ""))
    except ValueError:
        print("supervisor: invalid ntfy_url in config.json; ntfy disabled", flush=True)
        url = ""

    value = payload.get("game_dir")
    game_dir = Path(value) if isinstance(value, str) and "\0" not in value else None
    if value is not None and (game_dir is None or not game_dir.is_absolute()):
        print("supervisor: game_dir in config.json must be an absolute path; ignoring it", flush=True)
        game_dir = None
    return Config(ntfy_url=url, game_dir=game_dir)


def _ntfy_url(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError
    url = value.strip()
    if url:
        parts = urlsplit(url)
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or any(character.isspace() or ord(character) < 32 for character in url)):
            raise ValueError
    return url
