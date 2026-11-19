"""Service configuration, edited by the operator in app data."""

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..platform import Platform


@dataclass(frozen=True)
class Config:
    ntfy_url: str = ""


def config_path(os_: Platform) -> Path:
    return os_.app_data_dir() / "config.json"


def read_config(os_: Platform) -> Config:
    try:
        payload = json.loads(os_.read_shared(config_path(os_)))
        if not isinstance(payload, dict):
            raise ValueError
        value = payload.get("ntfy_url", "")
        if not isinstance(value, str):
            raise ValueError
        url = value.strip()
        if url:
            parts = urlsplit(url)
            if (parts.scheme not in ("http", "https") or not parts.hostname
                    or any(character.isspace() or ord(character) < 32 for character in url)):
                raise ValueError
        return Config(url)
    except FileNotFoundError:
        return Config()
    except (OSError, ValueError):
        print("supervisor: invalid or unreadable config.json; ntfy disabled", flush=True)
        return Config()
