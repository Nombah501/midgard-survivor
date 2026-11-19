"""Build the release assets for the current OS.

Tag v<version> must match the installed package version. PEP 440 prerelease
or development versions are GitHub prereleases. Assets are
midgard-farm-<version>-linux-x86_64.tar.gz and
midgard-farm-<version>-windows-x86_64.zip, each with a top-level midgard-farm/
and an <archive>.sha256 sidecar in sha256sum format.
"""

import argparse
import hashlib
import os
import platform
import shutil
import tarfile
from pathlib import Path

from packaging.version import Version

from midgard_farm.assets import version


def archive_release(onedir: Path, output: Path, tag: str) -> None:
    app_version = version()
    if tag != f"v{app_version}":
        raise SystemExit(f"Release tag {tag!r} does not match package version {app_version}; expected v{app_version}")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit(f"Release archives require x86_64, got {platform.machine()}")
    if onedir.name != "midgard-farm":
        raise SystemExit("The onedir must be named midgard-farm")
    output.mkdir(parents=True, exist_ok=True)
    base = f"midgard-farm-{app_version}"
    if os.name == "nt":
        archive = Path(shutil.make_archive(str(output / f"{base}-windows-x86_64"), "zip",
                                           root_dir=onedir.parent, base_dir=onedir.name))
    else:
        archive = output / f"{base}-linux-x86_64.tar.gz"
        # Keep executable modes and PyInstaller's relative library symlinks.
        with tarfile.open(archive, "w:gz", compresslevel=6) as bundle:
            bundle.add(onedir, arcname=onedir.name)
    with archive.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    archive.with_name(archive.name + ".sha256").write_bytes(f"{digest}  {archive.name}\n".encode("ascii"))
    print(f"{digest}  {archive.name} ({archive.stat().st_size / 2**20:.1f} MiB)")
    if github_output := os.environ.get("GITHUB_OUTPUT"):
        with Path(github_output).open("a", encoding="utf-8", newline="\n") as file:
            print(f"archive={archive.name}", file=file)
            print(f"prerelease={str(Version(app_version).is_prerelease).lower()}", file=file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("onedir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("tag")
    args = parser.parse_args()
    archive_release(args.onedir.resolve(strict=True), args.output.resolve(), args.tag)
