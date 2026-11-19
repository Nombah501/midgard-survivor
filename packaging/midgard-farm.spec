import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

scripts = Path(SPECPATH)
windows = sys.platform == "win32"
other_platform = "linux" if windows else "windows"
excludes = [f"midgard_farm.platform.{other_platform}"]

# Data comes from the installed wheel: setuptools owns the asset allowlist.
service = Analysis(
    [str(scripts / "service_entry.py")],
    datas=collect_data_files("midgard_farm", subdir="_farmer", include_py_files=True)
    + copy_metadata("midgard-farm"),
    excludes=excludes,
)
window = Analysis(
    [str(scripts / "window_entry.py")],
    hiddenimports=["PySide6.QtQuick"],  # QtQml's hook collects the QtQuick QML modules and Fusion.
    excludes=excludes,
)

# Two bootloaders preserve the service's direct task/unit command and keep Qt out
# of its runtime. COLLECT shares their external files in a single directory.
service_exe = EXE(PYZ(service.pure), service.scripts, exclude_binaries=True,
                  name="midgard-farm-service", console=not windows, upx=False)
window_exe = EXE(PYZ(window.pure), window.scripts, exclude_binaries=True,
                 name="midgard-farm", console=False, upx=False)
COLLECT(service_exe, window_exe, service.binaries, service.datas,
        window.binaries, window.datas, name="midgard-farm", upx=False)
