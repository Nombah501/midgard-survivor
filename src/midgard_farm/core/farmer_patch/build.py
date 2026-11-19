import hashlib
import json
import re
import runpy
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from ...assets import farmer_inputs
from ...platform import Platform
from .. import patch_info
from ..patch_info import INSTALLED_PACK, PatchInfo
from . import gdre as gdre_tools
from ._state import OFFICIAL_STATE, STATE, bridge_name, official_pack, patch_version, read_state
from .gdre import Gdre, sha256

BYTECODE = "ebc36a7"
_SOURCE_DIR = farmer_inputs()
_SOURCE_FILES = ("src/farmer.gd", "src/save_hook.gd", "tools/inject_hook.py", "tools/patch_player.py")
_SAVE = "scripts/autoload/save.gdc"
_PLAYER = "scripts/core/player.gdc"
_FARMER = "scripts/core/farmer.gdc"


class BuildFailed(Exception):
    """Building the farmer patch failed; see log_path for GDRE output."""

    def __init__(self, reason: str, log_path: Path):
        super().__init__(reason)
        self.log_path = log_path


class AnchorsBroken(BuildFailed):
    """A supported injector could not find its anchor in the decompiled game script."""


class _AnchorNotFound(Exception):
    pass


def _inputs(sources: Path | None) -> tuple[dict[str, str], int, str]:
    contents = {name: ((sources or _SOURCE_DIR) / name).read_text(encoding="utf-8") for name in _SOURCE_FILES}
    api = re.search(r"^const API_VERSION\s*:?=\s*(\d+)\b", contents["src/farmer.gd"], re.MULTILINE)
    if api is None:
        raise ValueError("API_VERSION is missing from farmer.gd")
    version = int(api[1])
    # UTF-8/LF source text under fixed relative names; sorted compact JSON
    # frames every input independently of checkout paths or host OS.
    encoded = json.dumps([BYTECODE, version, contents], sort_keys=True, separators=(",", ":")).encode("utf-8")
    return contents, version, hashlib.sha256(encoded).hexdigest()


def farmer_hash(sources: Path | None = None) -> str:
    """Fingerprint the same app-side inputs used by build(), excluding game files."""
    return _inputs(sources)[2]


def _command(gdre: Gdre, work: Path, log: TextIO, *args: str) -> subprocess.CompletedProcess[str]:
    print(f"GDRE {args!r}", file=log, flush=True)
    result = gdre.run(work, *args)
    print(result.stdout, file=log)
    return result


def _check(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode:
        raise ValueError(f"{action} (GDRE exit {result.returncode})")


def _extract(gdre: Gdre, work: Path, log: TextIO, pack: Path, resource: str, output: Path) -> Path | None:
    result = _command(gdre, work, log, f"--extract={pack}", f"--output={output}", f"--include=res://{resource}")
    if result.returncode == 1 and "Error: no files found that match includes" in result.stdout:
        return None
    _check(result, f"cannot extract {resource} from {pack.name}")
    script = output / resource
    if not script.is_file():
        raise ValueError(f"GDRE did not extract {resource} from {pack.name}")
    return script


def _decompile(
    os_: Platform, gdre: Gdre, log: TextIO, work: Path, packs: list[Path], resource: str,
) -> Path:
    for i, pack in enumerate(packs):
        script = _extract(gdre, work, log, pack, resource, work / "extract" / str(i))
        if script is not None:
            break
    else:
        raise ValueError(f"{resource} not found in any pack")

    # Content address the effective bytecode, not the whole mounted stack: a
    # changed base/bridge matters only if it changes the selected script.
    key = hashlib.sha256(f"{gdre.identity}:{BYTECODE}:{sha256(script)}".encode()).hexdigest()
    destination = work / Path(resource).with_suffix(".gd").name
    cache = patch_info.farmer_dir(os_) / "decompiled" / f"{key}.gd"
    if cache.is_file():
        log.write(f"Decompile cache hit for {resource}: {key}\n")
        destination.write_bytes(cache.read_bytes())
        return destination
    result = _command(gdre, work, log, f"--decompile={script}", f"--bytecode={BYTECODE}", f"--output={work}")
    _check(result, f"cannot decompile {resource}")
    data = destination.read_bytes()
    if not data:
        raise ValueError(f"decompiled {resource} is empty")
    cache.parent.mkdir(parents=True, exist_ok=True)
    os_.write_atomic(cache, data)
    return destination


def _inject(script: Path, log: TextIO, *args: Path) -> None:
    # These trusted, bundled injectors have a script-only interface. Run them
    # in-process so the frozen app needs neither an installed Python nor bash.
    argv = sys.argv
    sys.argv = [str(script), *(str(arg) for arg in args)]
    try:
        with redirect_stdout(log):
            runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        if isinstance(exc.code, str) and exc.code.endswith(" anchor not found"):
            raise _AnchorNotFound(exc.code) from exc
        if exc.code not in (None, 0):
            raise ValueError(f"{script.name}: {exc.code}") from exc
    finally:
        sys.argv = argv


def _build(
    os_: Platform, profile: Path, sources: Path | None, gdre: Gdre | None, work: Path, log: TextIO,
) -> PatchInfo:
    patches = profile.resolve() / "patches"
    _, state = read_state(patches / STATE)
    if state.get("file") == INSTALLED_PACK:
        _, state = read_state(patches / OFFICIAL_STATE)
    official = official_pack(patches, state)
    version, bridge = patch_version(state), bridge_name(state)
    bridge_path = patches / bridge
    has_bridge = bool(bridge) and bridge_path.is_file()
    patch_sha = sha256(official)
    bridge_sha = sha256(bridge_path) if has_bridge else ""
    executable = os_.game_executable().resolve()
    if not executable.is_file():
        raise ValueError(f"game not found at {executable}")
    base = executable.with_suffix(".pck")
    packs = [official]
    if has_bridge:
        packs.append(bridge_path)
    if base.is_file():
        packs.append(base)

    contents, api, fingerprint = _inputs(sources)
    for name, text in contents.items():
        path = work / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    gdre = gdre if gdre is not None else gdre_tools.prepare(os_, work / "gdre")
    save_script = _decompile(os_, gdre, log, work, packs, _SAVE)
    player_script = _decompile(os_, gdre, log, work, packs, _PLAYER)
    save_hooked = work / "save_hooked.gd"
    player_patched = work / "player_patched.gd"
    _inject(work / "tools/inject_hook.py", log, save_script, work / "src/save_hook.gd", save_hooked)
    _inject(work / "tools/patch_player.py", log, player_script, player_patched)
    # The bundled injectors use the platform's text-mode newline.
    for output in (save_hooked, player_patched):
        data = output.read_bytes()
        if b"\r\n" in data:
            output.write_bytes(data.replace(b"\r\n", b"\n"))
    resources = (_SAVE, _PLAYER, _FARMER)
    compiled = []
    for source in (save_hooked, player_patched, work / "src/farmer.gd"):
        result = _command(gdre, work, log, f"--compile={source}", f"--bytecode={BYTECODE}", f"--output={work}")
        _check(result, f"cannot compile {source.name}")
        script = work / source.with_suffix(".gdc").name
        if not script.is_file():
            raise ValueError(f"GDRE did not compile {source.name}")
        compiled.append(script)

    pack = work / INSTALLED_PACK
    patch_args = [f"--patch-file={script}=res://{res}" for script, res in zip(compiled, resources, strict=True)]
    result = _command(gdre, work, log, f"--pck-patch={official}", *patch_args, f"--output={pack}")
    _check(result, "cannot patch PCK")
    for script, res in zip(compiled, resources, strict=True):
        extracted = _extract(gdre, work, log, pack, res, work / "verify")
        if extracted is None or extracted.read_bytes() != script.read_bytes():
            raise ValueError(f"built PCK does not contain the compiled {res}")

    info = PatchInfo(
        official.name, version, patch_sha, bridge, bridge_sha, BYTECODE, api, fingerprint,
        sha256(pack), datetime.now(UTC).isoformat(timespec="seconds"),
    )
    os_.replace_atomic(pack, patch_info.built_pack_path(os_))
    patch_info.save(os_, patch_info.info_path(os_), info)
    return info


def build(os_: Platform, profile: Path, *, sources: Path | None = None, gdre: Gdre | None = None) -> PatchInfo:
    """Build the app's farmer patch without writing to the profile or game folder."""
    directory = patch_info.farmer_dir(os_)
    log_path = directory / "build.log"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (
            log_path.open("w", encoding="utf-8") as log,
            tempfile.TemporaryDirectory(dir=directory, ignore_cleanup_errors=True) as work,
        ):
            try:
                return _build(os_, profile, sources, gdre, Path(work), log)
            except Exception as exc:
                print(f"build: {exc}", file=log)
                raise
    except _AnchorNotFound as exc:
        raise AnchorsBroken(str(exc), log_path) from exc
    except Exception as exc:
        raise BuildFailed(str(exc), log_path) from exc
