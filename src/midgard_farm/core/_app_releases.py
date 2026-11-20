"""Download the private GitHub release without forwarding its credential."""

import hashlib
import json
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ..platform import Platform

_RELEASES = "https://api.github.com/repos/Nombah501/midgard-survivor/releases"
# Production release tags use X.Y.Z; also allow normalized PEP 440 post releases.
_VERSION = re.compile(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})(?:\.post(0|[1-9][0-9]{0,8}))?")


class ReleaseError(Exception):
    """A safe, credential-free reason to display in Updates."""


class TokenRejected(ReleaseError):
    pass


class _AssetsIncomplete(ReleaseError):
    """The latest release lacks a complete archive and checksum pair."""


def version_key(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, str) or not (match := _VERSION.fullmatch(value)):
        return None
    return tuple(int(part) if part is not None else -1 for part in match.groups())


def _open(token: str, url: str, accept: str):
    request = Request(url, headers={"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"})
    # GitHub can redirect private assets to a signed URL. Never forward the PAT.
    request.add_unredirected_header("Authorization", f"Bearer {token}")
    return urlopen(request, timeout=15)


@dataclass(frozen=True)
class Release:
    version: str
    name: str
    archive_id: int
    checksum_id: int


def latest(token: str, current: str, bad: tuple[str, ...], release_os: str) -> Release | None:
    installed = version_key(current)
    with _open(token, _RELEASES, "application/vnd.github+json") as response:
        rows = json.loads(response.read(8 << 20))
    if not isinstance(rows, list):
        raise ReleaseError("invalid GitHub releases response")
    candidates = []
    for row in rows:
        if not isinstance(row, dict) or row.get("draft") is not False or row.get("prerelease") is not False:
            continue
        tag = row.get("tag_name")
        if not isinstance(tag, str) or not tag.startswith("v"):
            continue
        version = tag[1:]
        key = version_key(version)
        if key is not None and installed is not None and key > installed and version not in bad:
            candidates.append((key, version, row))
    if not candidates:
        return None
    _, version, row = max(candidates, key=lambda candidate: candidate[0])
    extension = "zip" if release_os == "windows" else "tar.gz"
    name = f"midgard-farm-{version}-{release_os}-x86_64.{extension}"
    assets = row.get("assets")
    if not isinstance(assets, list):
        raise _AssetsIncomplete("missing release assets")
    ids = {asset["name"]: asset["id"] for asset in assets
           if isinstance(asset, dict) and isinstance(asset.get("name"), str)
           and type(asset.get("id")) is int and asset["id"] > 0}
    if name not in ids or name + ".sha256" not in ids:
        raise _AssetsIncomplete("missing release archive or checksum")
    return Release(version, name, ids[name], ids[name + ".sha256"])


def _member_path(name: str) -> PurePosixPath:
    name = name.rstrip("/")
    parts = name.split("/")
    if (not parts or parts[0] != "midgard-farm"
            or any(part in ("", ".", "..") or "\\" in part or ":" in part for part in parts)):
        raise ReleaseError("unsafe release archive path")
    return PurePosixPath(*parts)


def _extract(archive: Path, target: Path, *, windows: bool) -> Path:
    if windows:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                path = _member_path(member.filename)
                if any(part.endswith((".", " ")) or any(c in part for c in '<>"|?*') for part in path.parts):
                    raise ReleaseError("unsafe Windows release archive path")
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise ReleaseError("unexpected link in Windows release archive")
            bundle.extractall(target)
    else:
        def filter_member(member: tarfile.TarInfo, directory: str) -> tarfile.TarInfo | None:
            _member_path(member.name)
            return tarfile.data_filter(member, directory)

        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(target, filter=filter_member)
    return target / "midgard-farm"


def has_service(os_: Platform, directory: Path) -> bool:
    return not directory.is_symlink() and (directory / ("midgard-farm-service" + os_.executable_suffix)).is_file()


def download(os_: Platform, token: str, release: Release, versions: Path) -> None:
    with tempfile.TemporaryDirectory(dir=versions, prefix=".download-") as work:
        staging = Path(work)
        with _open(token, f"{_RELEASES}/assets/{release.checksum_id}", "application/octet-stream") as response:
            line = response.read(1024)
        if not (checksum := re.fullmatch(rb"([0-9a-fA-F]{64}) [ *]" + re.escape(release.name.encode()) + rb"\r?\n?", line)):
            raise ReleaseError("invalid release checksum sidecar")
        archive = staging / release.name
        with (_open(token, f"{_RELEASES}/assets/{release.archive_id}", "application/octet-stream") as response,
              archive.open("wb") as output):
            shutil.copyfileobj(response, output, length=1 << 20)
        with archive.open("rb") as output:
            digest = hashlib.file_digest(output, "sha256").hexdigest().encode()
        if digest != checksum[1].lower():
            raise ReleaseError("release archive checksum did not match")
        windows = os_.release_os == "windows"
        bundle = _extract(archive, staging, windows=windows)
        if (not has_service(os_, bundle) or not (bundle / ("midgard-farm" + os_.executable_suffix)).is_file()
                or not (bundle / "_internal").is_dir()):
            raise ReleaseError("incomplete release archive")
        destination = versions / release.version
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        os_.replace_atomic(bundle, destination)


def asset_key(release: Release) -> str:
    return f"{release.version}/{release.archive_id}/{release.checksum_id}"


def fetch(os_: Platform, token: str, current: str, bad: tuple[str, ...], versions: Path,
          *, verified: object, invalidate: Callable[[], None]) -> Release | None:
    try:
        release = latest(token, current, bad, os_.release_os)
        if release is not None:
            changed = asset_key(release) != verified
            if changed:
                invalidate()
            if changed or not has_service(os_, versions / release.version):
                download(os_, token, release, versions)
        return release
    except _AssetsIncomplete:
        invalidate()
        raise
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise TokenRejected("release token rejected; enter a new token") from None
        raise ReleaseError(f"GitHub returned HTTP {exc.code}") from None
    except (zipfile.BadZipFile, tarfile.TarError, EOFError):
        raise ReleaseError("invalid release archive") from None
    except (OSError, HTTPException):
        raise ReleaseError("release check could not reach GitHub or write the download") from None
    except (ValueError, RecursionError, TypeError):
        raise ReleaseError("invalid GitHub releases response") from None
