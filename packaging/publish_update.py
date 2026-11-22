"""Publish both verified stable assets and their minisign manifest to Cloudflare R2."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from midgard_farm.core import _app_releases as releases

_EXPIRY = 180 * 86400
_IMMUTABLE = "public, max-age=31536000, immutable"


def changelog_entry(path: Path, version: str) -> str:
    sections = re.split(r"^## \[([^\]\n]+)\][^\n]*\n", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    matches = [body.strip() for heading, body in zip(sections[1::2], sections[2::2], strict=True)
               if heading == version]
    if len(matches) != 1 or not matches[0]:
        raise ValueError(f"CHANGELOG.md needs one nonempty section headed ## [{version}]")
    return matches[0] + "\n"


def sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


class StorageError(Exception):
    def __init__(self, operation: str, code: str):
        super().__init__(f"R2 {operation} failed ({code})")
        self.code = code


class R2:
    def __init__(self, endpoint: str, bucket: str):
        if not re.fullmatch(r"https://[0-9a-f]{32}(?:\.(?:eu|fedramp|us))?\.r2\.cloudflarestorage\.com", endpoint):
            raise ValueError("R2_ENDPOINT must be the bucket's HTTPS S3 API endpoint")
        if not bucket:
            raise ValueError("R2_BUCKET is not configured")
        self.options = ["--endpoint-url", endpoint, "--region", "auto", "--output", "json",
                        "--no-cli-pager", "--no-cli-auto-prompt", "--bucket", bucket]

    def request(self, operation: str, key: str, *args: str) -> dict:
        result = subprocess.run(["aws", "s3api", operation, *self.options, "--key", key, *args],
                                capture_output=True, text=True, check=False,
                                env={k: v for k, v in os.environ.items() if k != "MINISIGN_SECRET_KEY"})
        if result.returncode:
            match = re.search(r"An error occurred \(([A-Za-z0-9]+)\)", result.stderr)
            raise StorageError(operation, match[1] if match else f"aws exit {result.returncode}")
        return json.loads(result.stdout)

    def get(self, key: str, path: Path, limit: int) -> str:
        # Include one extra byte to detect an unexpectedly oversized object.
        return self.request("get-object", key, "--range", f"bytes=0-{limit}", str(path))["ETag"]

    def put(self, key: str, path: Path, *options: str) -> None:
        self.request("put-object", key, "--body", str(path), *options)

    def put_immutable(self, key: str, path: Path, digest: str, scratch: Path) -> None:
        try:
            self.put(key, path, "--if-none-match", "*", "--cache-control", _IMMUTABLE,
                     "--content-type", "application/octet-stream")
        except StorageError as exc:
            if exc.code != "PreconditionFailed":
                raise
            size = path.stat().st_size
            existing = scratch / "existing-object"
            self.get(key, existing, size)
            if existing.stat().st_size != size or sha256(existing) != digest:
                raise ValueError(f"immutable R2 object does not match: {key}") from None


def sign(manifest: Path, signature: Path, secret: str) -> None:
    if not secret.strip():
        raise ValueError("MINISIGN_SECRET_KEY is not configured")
    # The private directory is 0700, and the key is removed even on failure.
    with tempfile.TemporaryDirectory(prefix="midgard-sign-") as work:
        key = Path(work) / "minisign.key"
        key.write_text(secret.rstrip() + "\n", encoding="utf-8")
        subprocess.run(["minisign", "-S", "-q", "-s", str(key), "-m", str(manifest), "-x", str(signature),
                        "-t", "Midgard Farm stable manifest v1"], input=b"", check=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "R2_", "MINISIGN_"))})


def publish(storage: R2, assets: Path, changelog: Path, version: str, sequence: int, secret: str) -> None:
    releases.update_base_url()  # Don't publish stable assets with an unprovisioned frozen client.
    version_id = releases.version_key(version)
    if version_id is None:
        raise ValueError("expected a stable release tag vX.Y.Z")
    with tempfile.TemporaryDirectory(prefix="midgard-publish-") as tmp:
        work = Path(tmp)
        manifest_path, sig_path = work / "manifest.json", work / "manifest.minisig"
        try:
            etag = storage.get(releases.MANIFEST_KEY, manifest_path, releases.MAX_MANIFEST_SIZE)
        except StorageError as exc:
            if exc.code != "NoSuchKey":
                raise
            condition = ("--if-none-match", "*")
        else:
            previous_bytes = manifest_path.read_bytes()
            if len(previous_bytes) > releases.MAX_MANIFEST_SIZE:
                raise ValueError("published manifest is too large")
            storage.get(releases.signature_key(hashlib.sha256(previous_bytes).hexdigest()), sig_path,
                        releases.MAX_SIGNATURE_SIZE)
            previous = releases.verify_manifest(previous_bytes, sig_path.read_bytes())
            if previous.sequence == sequence and previous.version == version and previous.expires_at > time.time():
                print(f"Stable update {version} (sequence {sequence}) is already published")
                return
            previous_version = releases.version_key(previous.version)
            if sequence <= previous.sequence or previous_version is None or version_id <= previous_version:
                raise ValueError("stable publish must advance both the saved sequence and release version")
            condition = ("--if-match", etag)
            sig_path.unlink()

        archives = {}
        for target in ("linux", "windows"):
            path = assets / releases.archive_name(version, target)
            archives[target] = releases.Archive(path.name, path.stat().st_size, sha256(path))
        data = (json.dumps({"schema": 1, "channel": releases.CHANNEL, "version": version, "sequence": sequence,
                            "expires_at": int(time.time()) + _EXPIRY, "changelog": changelog_entry(changelog, version),
                            "archives": {target: asdict(asset) for target, asset in archives.items()}},
                           ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        manifest_path.write_bytes(data)
        sign(manifest_path, sig_path, secret)
        # Verify with the exact runtime pin and parser before uploading anything.
        releases.verify_manifest(data, sig_path.read_bytes())
        for asset in archives.values():
            storage.put_immutable(asset.object_key, assets / asset.name, asset.sha256, work)
        storage.put_immutable(releases.signature_key(hashlib.sha256(data).hexdigest()), sig_path, sha256(sig_path), work)
        storage.put(releases.MANIFEST_KEY, manifest_path, *condition, "--cache-control", "no-store, no-transform",
                    "--content-type", "application/json")
        print(f"Published stable update {version} (sequence {sequence})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("changelog", type=Path)
    parser.add_argument("tag")
    parser.add_argument("sequence", type=int)
    args = parser.parse_args()
    try:
        for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET", "MINISIGN_SECRET_KEY"):
            if not os.environ.get(key):
                raise ValueError(f"{key} is not configured")
        if not args.tag.startswith("v"):
            raise ValueError("expected a stable release tag starting with v")
        publish(R2(os.environ["R2_ENDPOINT"], os.environ["R2_BUCKET"]), args.assets, args.changelog,
                args.tag[1:], args.sequence, os.environ["MINISIGN_SECRET_KEY"])
    except (OSError, ValueError, StorageError, releases.ReleaseError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"publish_update: {exc}") from None


if __name__ == "__main__":
    main()
