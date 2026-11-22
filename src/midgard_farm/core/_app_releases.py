"""Verify the stable App update manifest and stage an authenticated archive."""

import base64
import hashlib
import json
import re
import shutil
import stat
import tarfile
import tempfile
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from ..platform import Platform

# Signed update channel (ADR 0010): R2 bucket midgard-farm-release behind the Operator's domain.
UPDATE_BASE_URL = "https://updates.vibeauction.shop"
MINISIGN_PUBLIC_KEY = "RWQs+4Pjv3LjCQyZNEjrnUPsMD6V03qW2NsY8kWAfUmYf3YP3V52dJmz"
USER_AGENT = "MidgardFarm-Updater"
CHANNEL = "stable"
MANIFEST_KEY = f"{CHANNEL}/manifest.json"
MAX_MANIFEST_SIZE = 1 << 20
MAX_SIGNATURE_SIZE = 4096
_MAX_ARCHIVE_SIZE = 1 << 30
_MAX_SAFE_INTEGER = (1 << 53) - 1
_ARCHIVE_SUFFIXES = {"linux": "tar.gz", "windows": "zip"}
_SHA256 = re.compile(r"[0-9a-f]{64}")
# Production release tags use X.Y.Z; also allow normalized PEP 440 post releases.
_VERSION = re.compile(r"(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})(?:\.post(0|[1-9][0-9]{0,8}))?")


class ReleaseError(Exception):
    """A safe, credential-free reason to display in Updates."""


def version_key(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, str) or not (match := _VERSION.fullmatch(value)):
        return None
    return tuple(int(part) if part is not None else -1 for part in match.groups())


def archive_name(version: str, release_os: str) -> str:
    return f"midgard-farm-{version}-{release_os}-x86_64.{_ARCHIVE_SUFFIXES[release_os]}"


def signature_key(digest: str) -> str:
    return f"signatures/{digest}.minisig"


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl) -> None:
        return None


_HTTPS = build_opener(_NoRedirect())


def update_base_url() -> str:
    url = urlsplit(UPDATE_BASE_URL)
    if (url.scheme != "https" or not url.hostname or url.hostname.endswith(".invalid")
            or url.username is not None or url.password is not None or url.query or url.fragment):
        raise ReleaseError("App update domain is not configured")
    return UPDATE_BASE_URL.rstrip("/")


@contextmanager
def _open(key: str):
    # Cloudflare's Browser Integrity Check answers urllib's default User-Agent with 403 (error 1010).
    request = Request(f"{update_base_url()}/{key}",
                      headers={"Accept-Encoding": "identity", "User-Agent": USER_AGENT})
    try:
        with _HTTPS.open(request, timeout=15) as response:
            yield response
    except HTTPError as exc:
        exc.close()
        raise ReleaseError(f"update server returned HTTP {exc.code}") from None
    except HTTPException:
        raise ReleaseError("update server returned an incomplete response") from None


@dataclass(frozen=True)
class Archive:
    name: str
    size: int
    sha256: str

    @property
    def object_key(self) -> str:
        return f"archives/{self.sha256}/{self.name}"


@dataclass(frozen=True)
class Manifest:
    version: str
    sequence: int
    expires_at: int
    changelog: str
    archives: dict[str, Archive]


def verify_manifest(data: bytes, signature: bytes) -> Manifest:
    """Verify a minisign prehashed signature before parsing any signed metadata."""
    if not MINISIGN_PUBLIC_KEY:
        raise ReleaseError("App update verification key is not configured")
    if len(data) > MAX_MANIFEST_SIZE or len(signature) > MAX_SIGNATURE_SIZE:
        raise ReleaseError("update manifest or signature is too large")
    try:
        key = base64.b64decode(MINISIGN_PUBLIC_KEY, validate=True)
        untrusted, encoded_sig, trusted, encoded_global = signature.splitlines()
        sig = base64.b64decode(encoded_sig, validate=True)
        global_sig = base64.b64decode(encoded_global, validate=True)
        prefix = b"trusted comment: "
        if (len(key) != 42 or key[:2] != b"Ed" or len(sig) != 74 or sig[:2] != b"ED"
                or sig[2:10] != key[2:10] or len(global_sig) != 64
                or not untrusted.startswith(b"untrusted comment: ") or not trusted.startswith(prefix)):
            raise ValueError
        verifier = VerifyKey(key[10:])
        verifier.verify(hashlib.blake2b(data).digest(), sig[10:])
        verifier.verify(sig[10:] + trusted[len(prefix):], global_sig)
    except (ValueError, BadSignatureError):
        raise ReleaseError("invalid update manifest signature") from None

    try:
        row = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        raise ReleaseError("invalid update manifest JSON") from None
    if (not isinstance(row, dict) or type(row.get("schema")) is not int or row["schema"] != 1
            or row.get("channel") != CHANNEL or version_key(row.get("version")) is None
            or type(row.get("sequence")) is not int or not 1 <= row["sequence"] <= _MAX_SAFE_INTEGER
            or type(row.get("expires_at")) is not int or not 1 <= row["expires_at"] <= _MAX_SAFE_INTEGER
            or not isinstance(row.get("changelog"), str)):
        raise ReleaseError("invalid update manifest metadata")
    archive_rows = row.get("archives")
    if not isinstance(archive_rows, dict) or archive_rows.keys() != _ARCHIVE_SUFFIXES.keys():
        raise ReleaseError("update manifest must describe both OS archives")
    archives = {}
    version = row["version"]
    for os_, entry in archive_rows.items():
        if (not isinstance(entry, dict) or entry.get("name") != archive_name(version, os_)
                or type(entry.get("size")) is not int or not 1 <= entry["size"] <= _MAX_ARCHIVE_SIZE
                or not is_sha256(entry.get("sha256"))):
            raise ReleaseError("invalid update manifest archive metadata")
        archives[os_] = Archive(entry["name"], entry["size"], entry["sha256"])
    return Manifest(version, row["sequence"], row["expires_at"], row["changelog"], archives)


def get_manifest() -> tuple[Manifest, str]:
    if not MINISIGN_PUBLIC_KEY:
        raise ReleaseError("App update verification key is not configured")
    try:
        with _open(MANIFEST_KEY) as response:
            data = response.read(MAX_MANIFEST_SIZE + 1)
        if len(data) > MAX_MANIFEST_SIZE:
            raise ReleaseError("update manifest or signature is too large")
        digest = hashlib.sha256(data).hexdigest()
        with _open(signature_key(digest)) as response:
            signature = response.read(MAX_SIGNATURE_SIZE + 1)
    except OSError:
        raise ReleaseError("could not reach the App update server") from None
    manifest = verify_manifest(data, signature)
    if manifest.expires_at <= time.time():
        raise ReleaseError("update manifest has expired")
    return manifest, digest


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


def download(os_: Platform, version: str, asset: Archive, versions: Path) -> None:
    try:
        _download(os_, version, asset, versions)
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, ValueError):
        raise ReleaseError("invalid release archive") from None
    except OSError:
        raise ReleaseError("could not download or stage the release archive") from None


def _download(os_: Platform, version: str, asset: Archive, versions: Path) -> None:
    with tempfile.TemporaryDirectory(dir=versions, prefix=".download-") as work:
        staging = Path(work)
        archive = staging / asset.name
        digest = hashlib.sha256()
        remaining = asset.size
        with _open(asset.object_key) as response, archive.open("wb") as output:
            while chunk := response.read(min(1 << 20, remaining + 1)):
                remaining -= len(chunk)
                if remaining < 0:
                    raise ReleaseError("release archive size did not match")
                output.write(chunk)
                digest.update(chunk)
        if remaining:
            raise ReleaseError("release archive size did not match")
        if digest.hexdigest() != asset.sha256:
            raise ReleaseError("release archive SHA-256 did not match")
        windows = os_.release_os == "windows"
        bundle = _extract(archive, staging, windows=windows)
        if (not has_service(os_, bundle) or not (bundle / ("midgard-farm" + os_.executable_suffix)).is_file()
                or not (bundle / "_internal").is_dir()):
            raise ReleaseError("incomplete release archive")
        destination = versions / version
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        os_.replace_atomic(bundle, destination)
