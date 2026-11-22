"""Fetch the published stable channel exactly as an installed App does and check it serves VERSION."""

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from midgard_farm.core import _app_releases as releases  # noqa: E402


def check(version: str) -> None:
    manifest = releases.get_manifest()[0]
    if manifest.version != version:
        raise SystemExit(f"stable manifest serves {manifest.version}, expected {version}")
    for release_os, asset in sorted(manifest.archives.items()):
        digest, size = hashlib.sha256(), 0
        with releases._open(asset.object_key) as response:
            while chunk := response.read(1 << 20):
                digest.update(chunk)
                size += len(chunk)
        if (size, digest.hexdigest()) != (asset.size, asset.sha256):
            raise SystemExit(f"{release_os} archive {asset.name} does not match the signed manifest")
        print(f"{release_os}: {asset.name} {size} bytes, SHA-256 verified")
    print(f"stable channel serves {manifest.version} (sequence {manifest.sequence})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="expected version, e.g. 0.4.1")
    check(parser.parse_args().version.removeprefix("v"))
