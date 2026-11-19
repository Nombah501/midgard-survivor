import hashlib
import zipfile

import pytest

from midgard_farm import platform
from midgard_farm.core.farmer_patch import gdre


def test_gdre_checks_download_and_cache_before_unpacking(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "app data"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app data"))
    os_ = platform.current()
    upstream = tmp_path / "release.zip"
    with zipfile.ZipFile(upstream, "w") as archive:
        archive.writestr("fake_gdre", b"some fake GDRE executable")
        archive.writestr("gdre_tools.pck", b"required companion data")
    good_archive = upstream.read_bytes()
    checksum = hashlib.sha256(good_archive).hexdigest()
    url = upstream.as_uri()
    monkeypatch.setitem(gdre.RELEASES, os_.release_os, gdre.Release(url, "0" * 64, "fake_gdre"))

    with pytest.raises(gdre.GdreError, match="SHA-256 mismatch"):
        gdre.prepare(os_, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()
    assert not list(os_.app_data_dir().rglob("*.zip"))

    monkeypatch.setitem(gdre.RELEASES, os_.release_os, gdre.Release(url, checksum, "fake_gdre"))
    for name in ("first", "second"):
        work = tmp_path / name
        result = gdre.prepare(os_, work)
        assert result.identity == checksum
        assert (work / "fake_gdre").read_bytes() == b"some fake GDRE executable"
        assert (work / "gdre_tools.pck").read_bytes() == b"required companion data"
        upstream.unlink(missing_ok=True)  # second call must use the cached release

    cached, = os_.app_data_dir().rglob("*.zip")
    cached.write_bytes(b"corrupt cache entry")
    upstream.write_bytes(good_archive)
    recovered = tmp_path / "recovered"
    gdre.prepare(os_, recovered)
    assert (recovered / "fake_gdre").read_bytes() == b"some fake GDRE executable"
    assert cached.read_bytes() == good_archive

    cached.write_bytes(b"corrupt cache entry again")
    upstream.write_bytes(b"corrupt replacement download")
    with pytest.raises(gdre.GdreError, match="SHA-256 mismatch"):
        gdre.prepare(os_, tmp_path / "tampered")
    assert not (tmp_path / "tampered").exists()
    assert not cached.exists()
