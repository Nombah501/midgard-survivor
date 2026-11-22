"""Test the stable publishing contract without a real R2 bucket or release credentials."""

import hashlib
import importlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from midgard_farm.core import _app_releases as releases
from test_app_update import FakeReleases


@pytest.fixture
def publisher(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "packaging"))
    return importlib.import_module("publish_update")


def make_archives(assets, version):
    assets.mkdir(exist_ok=True)
    for target, extension in (("linux", "tar.gz"), ("windows", "zip")):
        (assets / f"midgard-farm-{version}-{target}-x86_64.{extension}").write_bytes(target.encode())


class FakeBucket:
    def __init__(self, publisher, monkeypatch):
        self.objects = {}
        self.writes = []
        self.storage = publisher.R2("https://" + "a" * 32 + ".r2.cloudflarestorage.com", "fixture")
        self.errors = publisher.StorageError
        monkeypatch.setattr(self.storage, "request", self.request)

    def request(self, operation, key, *args):
        if operation == "get-object":
            if key not in self.objects:
                raise self.errors(operation, "NoSuchKey")
            range_end = int(args[1].rsplit("-", 1)[1])
            Path(args[2]).write_bytes(self.objects[key][:range_end + 1])
            return {"ETag": self.etag(key)}
        assert operation == "put-object" and args[0] == "--body"
        if "--if-none-match" in args:
            assert args[args.index("--if-none-match") + 1] == "*"
            if key in self.objects:
                raise self.errors(operation, "PreconditionFailed")
        else:
            assert args[args.index("--if-match") + 1] == self.etag(key)
        self.objects[key] = Path(args[1]).read_bytes()
        self.writes.append((key, args[2:]))
        return {}

    def etag(self, key):
        return '"' + hashlib.sha256(self.objects[key]).hexdigest() + '"'


@pytest.mark.parametrize("use_minisign", [False, pytest.param(
    True, marks=pytest.mark.skipif(not shutil.which("minisign"), reason="minisign CLI not installed"),
)])
def test_publishes_both_archives_and_their_signature_before_advancing_manifest(publisher, tmp_path, monkeypatch,
                                                                             use_minisign):
    assets = tmp_path / "assets"
    make_archives(assets, "2.0.0")
    make_archives(assets, "2.1.0")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [2.1.0] - Unreleased\n\n- New.\n\n## [2.0.0]\n\n- Old.\n",
                         encoding="utf-8")
    if use_minisign:
        pub, key = tmp_path / "fixture.pub", tmp_path / "fixture.key"
        subprocess.run(["minisign", "-G", "-W", "-p", pub, "-s", key], check=True)
        public_key, secret = pub.read_text().splitlines()[1], key.read_text()
    else:
        public_key, secret = FakeReleases.public_key, "fixture"
        monkeypatch.setattr(publisher, "sign", lambda data, sig, _: sig.write_bytes(FakeReleases.sign(data.read_bytes())))
    monkeypatch.setattr(releases, "MINISIGN_PUBLIC_KEY", public_key)
    monkeypatch.setattr(releases, "UPDATE_BASE_URL", "https://updates.test")
    bucket = FakeBucket(publisher, monkeypatch)
    publisher.publish(bucket.storage, assets, changelog, "2.0.0", 12, secret)
    first = bucket.objects["stable/manifest.json"]
    first_writes = list(bucket.writes)
    publisher.publish(bucket.storage, assets, changelog, "2.0.0", 12, secret)
    with pytest.raises(ValueError, match="advance both"):
        publisher.publish(bucket.storage, assets, changelog, "2.1.0", 11, secret)
    with pytest.raises(ValueError, match="advance both"):
        publisher.publish(bucket.storage, assets, changelog, "2.0.0", 13, secret)
    assert bucket.writes == first_writes
    assert bucket.objects["stable/manifest.json"] == first

    publisher.publish(bucket.storage, assets, changelog, "2.1.0", 14, secret)
    manifest_bytes = bucket.objects["stable/manifest.json"]
    manifest = json.loads(manifest_bytes)
    assert manifest["channel"] == "stable" and manifest["sequence"] == 14 and manifest["version"] == "2.1.0"
    assert manifest["changelog"] == "- New.\n"
    assert time.time() < manifest["expires_at"] < time.time() + 181 * 86400
    signature_key = "signatures/" + hashlib.sha256(manifest_bytes).hexdigest() + ".minisig"
    writes = bucket.writes[len(first_writes):]
    keys = [key for key, _ in writes]
    assert keys[2:] == [signature_key, "stable/manifest.json"]
    assert "--if-match" in writes[-1][1] and "no-store, no-transform" in writes[-1][1]
    for target, key in zip(("linux", "windows"), keys[:2], strict=True):
        asset = manifest["archives"][target]
        content = target.encode()
        assert bucket.objects[key] == content
        assert key == f"archives/{hashlib.sha256(content).hexdigest()}/{asset['name']}"
        assert asset["size"] == len(content)
        assert asset["sha256"] == hashlib.sha256(content).hexdigest()


def test_immutable_archive_retry_checks_bytes_without_overwriting(publisher, tmp_path, monkeypatch):
    bucket = FakeBucket(publisher, monkeypatch)
    archive = tmp_path / "archive"
    archive.write_bytes(b"payload")
    key, digest = "archives/test", hashlib.sha256(archive.read_bytes()).hexdigest()
    bucket.storage.put_immutable(key, archive, digest, tmp_path)
    bucket.storage.put_immutable(key, archive, digest, tmp_path)
    assert len(bucket.writes) == 1
    bucket.objects[key] = b"corrupt"
    with pytest.raises(ValueError, match="immutable R2 object does not match"):
        bucket.storage.put_immutable(key, archive, digest, tmp_path)
    assert bucket.objects[key] == b"corrupt"
