"""Exercise a built onedir from outside the checkout, without Python on PATH."""

import argparse
import json
import os
import shutil
import struct
import subprocess
import tempfile
import tomllib
from pathlib import Path
from xml.etree import ElementTree

from midgard_farm.core.farmer_patch import farmer_hash
from qt_bundle import keep_qt_file

_ROOT = Path(__file__).resolve().parent.parent


def run_role(executable: Path, flag: str, home: Path, env: dict[str, str]) -> dict:
    report = home / f"{executable.stem}.json"
    result = subprocess.run([executable, flag, report], cwd=home, env=env, timeout=60,
                            capture_output=True, encoding="utf-8", errors="replace")
    output = report.read_text(encoding="utf-8") if report.exists() else "no report"
    if result.returncode or not report.exists():
        raise RuntimeError(f"{executable.name}: exit {result.returncode}: {output}\n"
                           f"{result.stdout}{result.stderr}")
    return json.loads(output)


def check_registration(executable: Path, definition: str, env: dict[str, str], home: Path) -> None:
    if os.name == "nt":
        with executable.open("rb") as file:
            file.seek(0x3C)
            pe_offset, = struct.unpack("<I", file.read(4))
            file.seek(pe_offset + 4 + 20 + 68)  # PE signature, COFF header, then Subsystem field.
            subsystem, = struct.unpack("<H", file.read(2))
        assert subsystem == 2, "The scheduled service must use the Windows GUI subsystem"
        task = ElementTree.fromstring(definition)
        action = task.find(".//{*}Exec")
        assert action is not None
        assert action.findtext("{*}Command") == str(executable), definition
        assert action.findtext("{*}WorkingDirectory") == str(executable.parent), definition
        assert action.find("{*}Arguments") is None, definition
    else:
        printed = subprocess.run([executable, "--print-unit"], cwd=home, env=env, timeout=60,
                                 check=True, capture_output=True, text=True).stdout
        assert printed == definition
        escaped = str(executable).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
        assert f'ExecStart="{escaped}"' in definition.splitlines(), definition


def check_qt_files(onedir: Path) -> float:
    internal = onedir / "_internal"
    rejected = []
    internal_files = set()
    size = 0
    platforms = set()
    for path in onedir.rglob("*"):
        if not path.is_file():
            continue
        if not path.is_symlink():
            size += path.stat().st_size
        if path.is_relative_to(internal):
            relative = path.relative_to(internal)
            internal_files.add(relative.name.lower())
            if not keep_qt_file(relative.as_posix()):
                rejected.append(relative)
        if path.parent.name == "platforms":
            platforms.add(path.stem.removeprefix("lib"))
    assert not rejected, f"Unexpected Qt modules or plugins: {sorted(rejected)}"
    required = {"qoffscreen", "qwindows"} if os.name == "nt" else {"qoffscreen", "qxcb", "qwayland"}
    assert required <= platforms, f"Missing desktop platform plugins: {required - platforms}"
    qt = internal / "PySide6"
    if os.name != "nt":
        qt /= "Qt"
    for style in ("Basic", "Fusion"):
        impl = qt / "qml" / "QtQuick" / "Controls" / style / "impl"
        plugin = f"qtquickcontrols2{style.lower()}styleimplplugin"
        library = f"qt6quickcontrols2{style.lower()}styleimpl"
        if os.name == "nt":
            plugin, library = f"{plugin}.dll", f"{library}.dll"
        else:
            plugin, library = f"lib{plugin}.so", f"lib{library}.so.6"
        for path in (impl / "qmldir", impl / plugin):
            assert path.is_file(), f"Missing Qt style implementation file: {path.relative_to(internal)}"
        assert library in internal_files, f"Missing Qt style implementation library: {library}"
    return size / 2**20


def check(onedir: Path) -> None:
    # Windows temp paths can use an 8.3 alias while the child reports the long path.
    onedir = onedir.resolve(strict=True)
    size_mib = check_qt_files(onedir)
    checkout = _ROOT / "farmer"
    version = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    presets = sorted(checkout.glob("presets/*.json"))
    expected_assets = [checkout / name for name in (
        "src/farmer.gd", "src/save_hook.gd", "tools/inject_hook.py", "tools/patch_player.py", "targets.json",
    )] + presets
    expected_hash = farmer_hash(checkout)
    expected_characters = {row["label"] for row in json.loads((checkout / "targets.json").read_bytes())["characters"].values()}
    suffix = ".exe" if os.name == "nt" else ""

    with tempfile.TemporaryDirectory(prefix="midgard farm smoke ") as directory:
        home = Path(directory)
        empty = home / "empty-path"
        empty.mkdir()
        env = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
                    "QML_IMPORT_PATH", "QML2_IMPORT_PATH", "QT_QUICK_CONTROLS_STYLE"):
            env.pop(key, None)
        env.update(PATH=str(empty), HOME=str(home), USERPROFILE=str(home), XDG_CONFIG_HOME=str(home / "config"),
                   XDG_DATA_HOME=str(home / "data"), XDG_CACHE_HOME=str(home / "cache"),
                   APPDATA=str(home / "roaming"), LOCALAPPDATA=str(home / "local"),
                   QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software")
        if os.name == "nt":
            env["QT_QPA_FONTDIR"] = str(Path(os.environ["SystemRoot"]) / "Fonts")
        assert not any(shutil.which(name, path=env["PATH"]) for name in ("python", "python3", "py"))

        service = onedir / f"midgard-farm-service{suffix}"
        service_report = run_role(service, "--self-check", home, env)
        assert service_report["version"] == version, service_report
        assert service_report["farmer_hash"] == expected_hash, service_report
        inputs = Path(service_report["inputs"]).resolve(strict=True)
        assert inputs.is_relative_to(onedir), inputs
        expected = {source.relative_to(checkout): source.read_bytes() for source in expected_assets}
        actual = {path.relative_to(inputs): path.read_bytes() for path in inputs.rglob("*") if path.is_file()}
        assert actual.keys() == expected.keys(), actual.keys() ^ expected.keys()
        differing = [name for name in expected if expected[name] != actual[name]]
        assert not differing, differing
        check_registration(service, service_report["registration"], env, home)

        window = run_role(onedir / f"midgard-farm{suffix}", "--smoke-test", home, env)
        assert window["loaded"] and not window["messages"], window
        assert window["version"] == version, window
        assert window["presets"] == [path.name for path in presets], window
        assert expected_characters <= set(window["characters"]), window
    print(f"{version}: {size_mib:.1f} MiB onedir; service, registration command and offscreen QML passed; "
          f"Farmer hash {expected_hash}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="onedir or release archive")
    bundle = parser.parse_args().bundle.resolve(strict=True)
    if bundle.is_dir():
        check(bundle)
    else:
        with tempfile.TemporaryDirectory(prefix="midgard farm extracted ") as directory:
            shutil.unpack_archive(bundle, directory, filter="data" if bundle.name.endswith(".tar.gz") else None)
            root = Path(directory)
            onedir = root / "midgard-farm"
            assert list(root.iterdir()) == [onedir] and onedir.is_dir(), "Archive must contain only midgard-farm/"
            check(onedir)
