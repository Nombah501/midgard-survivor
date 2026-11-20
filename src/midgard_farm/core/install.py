"""Install an unpacked release and launch the version selected by its current pointer."""

import filecmp
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from pathlib import Path

from ..platform import LockHeld, Platform
from .farmer_patch import GameRunning, restore
from .farmer_patch._state import OFFICIAL_STATE, STATE
from .patch_info import INSTALLED_PACK
from .profile import AmbiguousProfile

_CURRENT = "current"
_TOKEN = "release-token"
_LAUNCHER = "midgard-farm-launcher"
_SERVICE = "midgard-farm-service"
_VERSION = re.compile(
    r"(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc)[0-9]+)?(?:\.post[0-9]+)?"
    r"(?:\.dev[0-9]+)?(?:\+[a-z0-9]+(?:\.[a-z0-9]+)*)?"
)


class SetupError(Exception):
    """The release, its pointer or its installation could not be used."""


def _version_dir(data: Path, version: str) -> Path:
    if not _VERSION.fullmatch(version):
        raise SetupError("expected a release version such as 1.2.3")
    return data / "versions" / version


def service_registration_command(os_: Platform) -> list[str]:
    """The same stable command for setup registration and its read-only preview."""
    return [str(os_.app_data_dir().resolve() / "bin" / (_LAUNCHER + os_.executable_suffix))]


def current_service(os_: Platform) -> Path:
    """Resolve exactly the version selected by `current`, without a fallback."""
    data = os_.app_data_dir()
    pointer = data / _CURRENT
    try:
        version = os_.read_shared(pointer).decode("utf-8").strip()
        executable = _version_dir(data, version) / (_SERVICE + os_.executable_suffix)
    except (OSError, UnicodeError, SetupError) as exc:
        raise SetupError(f"cannot read current release pointer at {pointer}: {exc}") from exc
    if not executable.is_file():
        raise SetupError(f"current release {version} has no service executable at {executable}")
    return executable


def launch_current(os_: Platform, args: Sequence[str]) -> int:
    try:
        return os_.run_service_binary([str(current_service(os_)), *args])
    except (OSError, RuntimeError, SetupError, subprocess.SubprocessError) as exc:
        os_.report_launcher_error(f"midgard-farm-launcher: {exc}")
        return 1


def _same_tree(a: Path, b: Path) -> bool:
    if not b.is_dir():
        return False
    comparison = filecmp.dircmp(a, b, shallow=False)
    return not (comparison.left_only or comparison.right_only or comparison.diff_files
                or comparison.funny_files or comparison.common_funny) and all(
        _same_tree(a / name, b / name) for name in comparison.common_dirs
    )


def _copy_onedir(os_: Platform, source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".setup-") as temporary:
        staged = Path(temporary) / "release"
        shutil.copytree(source, staged, symlinks=True)
        if not target.exists():
            os_.replace_atomic(staged, target)
            return
        previous = staged.with_name("previous")
        os_.replace_atomic(target, previous)
        try:
            os_.replace_atomic(staged, target)
        except OSError:
            os_.replace_atomic(previous, target)
            raise


def _bundle_complete(path: Path, suffix: str) -> bool:
    launcher = path / "launcher"
    executables = [
        path / (name + suffix) for name in ("midgard-farm", _SERVICE, "midgard-farm-setup")
    ] + [launcher / (_LAUNCHER + suffix)]
    return (not path.is_symlink() and (path / "_internal").is_dir() and (launcher / "_internal").is_dir()
            and all(exe.is_file() and exe.stat().st_size > 0 for exe in executables))


def install(os_: Platform, source: Path, version: str, prompt_token: Callable[[], str]) -> Path:
    data, source = os_.app_data_dir().resolve(), source.resolve()
    target = _version_dir(data, version)
    suffix = os_.executable_suffix
    if not _bundle_complete(source, suffix):
        raise SetupError("run setup from a complete unpacked Midgard Farm release")
    if target != source and target.is_relative_to(source):
        raise SetupError("unpack the release outside the app's data directory")
    data.mkdir(parents=True, exist_ok=True)
    token_file = data / _TOKEN
    if token_file.is_symlink():
        raise SetupError("the release-token must be a regular file in the app's data directory")
    try:
        token_present = bool(os_.read_shared(token_file).strip())
    except FileNotFoundError:
        token_present = False
    if not token_present:
        token = prompt_token().strip()
        if not token or not token.isprintable() or any(character.isspace() for character in token):
            raise SetupError("enter a non-empty read-only release token without whitespace")
        # Platform.write_atomic starts from mkstemp (0600 on Linux); no token in argv or logs.
        os_.write_atomic(token_file, (token + "\n").encode("utf-8"))

    if not _bundle_complete(target, suffix):
        if target == source:
            raise SetupError("the installed release is incomplete; rerun setup from a complete unpacked release")
        _copy_onedir(os_, source, target)
        if not _bundle_complete(target, suffix):
            raise SetupError(f"the installed release is incomplete at {target}")
    bootstrap = data / "bin"
    if not _same_tree(source / "launcher", bootstrap):
        try:
            with os_.acquire_lock(data / "service.lock"):
                _copy_onedir(os_, source / "launcher", bootstrap)
        except LockHeld as exc:
            raise SetupError("stop the Midgard Farm service before refreshing its launcher, then rerun setup") from exc
    pointer = data / _CURRENT
    selected = (version + "\n").encode("utf-8")
    try:
        previous = os_.read_shared(pointer)
    except FileNotFoundError:
        previous = None
    if previous != selected:
        os_.write_atomic(pointer, selected)
    os_.register_service(service_registration_command(os_))
    return target


def _profile_for_restore(user_data_root: Path) -> Path | None:
    try:
        profiles = sorted(
            profile for profile in user_data_root.iterdir()
            if (profile / "profile.json").is_file()
            and any((profile / "patches" / marker).is_file() for marker in (STATE, OFFICIAL_STATE, INSTALLED_PACK))
        )
    except FileNotFoundError:
        return None
    if len(profiles) > 1:
        names = ", ".join(profile.name for profile in profiles)
        raise AmbiguousProfile(f"cannot restore the official patch: several profiles under {user_data_root}: {names}")
    return profiles[0] if profiles else None


def uninstall(os_: Platform) -> None:
    if os_.game_running():
        raise GameRunning("the game is running; close it first")
    os_.unregister_service()
    profile = _profile_for_restore(os_.godot_user_data_root())
    if profile is None:
        return
    data = os_.app_data_dir()
    service_lock = os_.acquire_lock(data / "service.lock") if data.is_dir() else nullcontext()
    with (
        service_lock,
        os_.acquire_lock(profile / "farmer_supervisor.lock"),
        os_.acquire_lock(profile / "farmer.run.lock"),
    ):
        restore(os_, profile)
