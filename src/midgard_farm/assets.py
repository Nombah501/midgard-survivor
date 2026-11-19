"""Resolve the app's immutable inputs in a checkout, wheel, or frozen onedir."""

import sys
import tomllib
from importlib.metadata import version as distribution_version
from pathlib import Path


def checkout_root() -> Path | None:
    if getattr(sys, "frozen", False):
        return None
    src = Path(__file__).resolve().parent.parent
    if src.name == "src" and (src.parent / "pyproject.toml").is_file():
        return src.parent
    return None


def farmer_inputs() -> Path:
    if (root := checkout_root()) is not None:
        return root / "farmer"
    return Path(__file__).resolve().with_name("_farmer")


def presets_dir() -> Path:
    return farmer_inputs() / "presets"


def targets_path() -> Path:
    return farmer_inputs() / "targets.json"


def version() -> str:
    if (root := checkout_root()) is not None:
        with (root / "pyproject.toml").open("rb") as file:
            return str(tomllib.load(file)["project"]["version"])
    return distribution_version("midgard-farm")
