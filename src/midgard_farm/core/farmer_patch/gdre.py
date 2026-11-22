"""Pinned GDRE distribution and its headless command interface."""

import hashlib
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

from ...platform import Platform

_VERSION = "v2.7.4"
_URL = f"https://github.com/GDRETools/gdsdecomp/releases/download/{_VERSION}"


class GdreError(Exception):
    """The pinned GDRE release could not be prepared."""


@dataclass(frozen=True)
class Release:
    url: str
    sha256: str
    executable: str


# Archive SHA-256s published by GitHub on the v2.7.4 release assets.
RELEASES = {
    "linux": Release(
        f"{_URL}/GDRE_tools-{_VERSION}-linux.zip",
        "3dc4f1244dda62e41e0c952ac00a69e60e07f3b0d5a211164806bf9d41a54758",
        "gdre_tools.x86_64",
    ),
    "windows": Release(
        f"{_URL}/GDRE_tools-{_VERSION}-windows.zip",
        "af24c563eee501effb194d83595de64696c32547b2246034dbfb891a24bfa0ad",
        "gdre_tools.exe",
    ),
}


@dataclass(frozen=True)
class Gdre:
    command: tuple[str, ...]
    identity: str  # Identifies the GDRE binary and its companion resources for decompile caching.

    def run(self, work: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self.command, "--headless", *args], cwd=work, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", timeout=300,
        )


def sha256(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _extract_verified(path: Path, expected_sha256: str, destination: Path) -> bool:
    with path.open("rb") as archive:
        if hashlib.file_digest(archive, "sha256").hexdigest() != expected_sha256:
            return False
        archive.seek(0)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
    return True


def cached_archive(os_: Platform) -> Path:
    """Locate the pinned archive without creating its cache directory."""
    release = RELEASES[os_.release_os]
    return os_.app_data_dir() / "gdre" / _VERSION / release.url.rsplit("/", 1)[-1]


def prepare(os_: Platform, destination: Path) -> Gdre:
    """Check the cached ZIP before unpacking; never execute a cached loose binary."""
    release = RELEASES[os_.release_os]
    cached = cached_archive(os_)
    cache = cached.parent
    cache.mkdir(parents=True, exist_ok=True)
    try:
        cache_ok = False
        if cached.exists():
            cache_ok = _extract_verified(cached, release.sha256, destination)
            if not cache_ok:
                cached.unlink(missing_ok=True)
        if not cache_ok:
            with tempfile.TemporaryDirectory(dir=cache, prefix=".download-") as staged:
                src = Path(staged) / cached.name
                with urlopen(release.url, timeout=60) as response, src.open("wb") as output:
                    shutil.copyfileobj(response, output)
                if not _extract_verified(src, release.sha256, destination):
                    raise GdreError(f"GDRE archive SHA-256 mismatch: {src}")
                os_.replace_atomic(src, cached)
        executable = destination / release.executable
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    except (OSError, zipfile.BadZipFile) as exc:
        raise GdreError(f"cannot prepare GDRE {_VERSION}: {exc}") from exc
    return Gdre((str(executable.resolve()),), release.sha256)
