"""Everything that differs between Linux and Windows, behind one interface.

The core asks `current()` for the implementation and never branches on the OS.
"""

import abc
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

type NotificationPriority = Literal["low", "normal", "high"]


class LockHeld(Exception):
    """Another process holds the single-instance lock."""


class NetworkIsolationError(OSError):
    """A supervised Linux game cannot enter its own network namespace."""


class InstanceLock(abc.ABC):
    """A held single-instance lock; the OS frees it when the holder dies."""

    @abc.abstractmethod
    def release(self) -> None: ...

    def __enter__(self) -> "InstanceLock":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


class ProcessTree(abc.ABC):
    """A started process and every descendant it spawns.

    Descendants can outlive the root, so end every tree with `kill()`, also
    after `wait()`: it ends stragglers and frees the tree's OS resources.
    """

    popen: subprocess.Popen

    @abc.abstractmethod
    def kill(self) -> None:
        """Kill the whole tree, grandchildren included, and reap the root. Idempotent."""

    @abc.abstractmethod
    def wait(self, timeout: float | None = None) -> int:
        """Wait for the root to exit on its own and return its exit code."""

    def __enter__(self) -> "ProcessTree":
        return self

    def __exit__(self, *exc) -> None:
        self.kill()


class Platform(abc.ABC):
    release_os: str
    """OS id for picking per-OS release assets, e.g. GDRE."""

    game_exit_status_reliable: bool
    """Whether the game exit code can veto an otherwise clean terminal status."""

    game_exe_name: str
    """File name of the game executable on this OS."""

    @abc.abstractmethod
    def godot_user_data_root(self) -> Path:
        """Godot's root for `user://` folders of apps without a custom user dir."""

    @abc.abstractmethod
    def godot_sandbox(self, data_home: Path) -> tuple[Path, dict[str, str]]:
        """Return the Godot user-data root and child environment for an isolated data home."""

    def link_sandbox_pack(self, source: Path, target: Path) -> None:
        """Hard-link an immutable pack, or copy it where hard links are unavailable."""
        source = source.resolve(strict=True)
        try:
            target.hardlink_to(source)
        except OSError:
            # Cross-volume hard links fail, and symlinks can require elevation on Windows.
            shutil.copyfile(source, target)

    @abc.abstractmethod
    def app_data_dir(self) -> Path:
        """This app's per-user data directory."""

    @abc.abstractmethod
    def default_game_dir(self) -> Path:
        """Where the game is installed when `GAME_DIR` is not set."""

    def game_executable(self) -> Path:
        game_dir = os.environ.get("GAME_DIR")
        return (Path(game_dir) if game_dir else self.default_game_dir()) / self.game_exe_name

    @abc.abstractmethod
    def game_pids(self) -> set[int]:
        """Processes running the game executable, from any folder."""

    def game_running(self) -> bool:
        return bool(self.game_pids())

    @abc.abstractmethod
    def notify_desktop(self, title: str, message: str, priority: NotificationPriority) -> None:
        """Deliver a desktop notification for the signed-in operator."""

    @abc.abstractmethod
    def acquire_lock(self, path: str | os.PathLike) -> InstanceLock:
        """Take the exclusive lock on `path` without waiting; raise LockHeld if taken."""

    @abc.abstractmethod
    def check_network_isolation(self) -> str | None:
        """Raise if isolation cannot be set up; return an operator warning if unsupported."""

    @abc.abstractmethod
    def spawn_tree(self, argv: Sequence[str], *, isolate_network: bool = False, **popen_kwargs) -> ProcessTree:
        """Start a killable group and, when requested, isolate its network where supported."""

    @abc.abstractmethod
    def replace_atomic(self, src: str | os.PathLike, dst: str | os.PathLike) -> None:
        """Replace `dst` with `src` in a single OS operation, durably."""

    def read_shared(self, path: Path, *, retry_missing: bool = False) -> bytes:
        """Read a file that another process may be replacing."""
        return path.read_bytes()

    def write_atomic(self, path: str | os.PathLike, data: bytes) -> None:
        """Write `data` to `path` so readers see the old or the new content, never a mix."""
        path = Path(path)
        # A unique name per call: concurrent writers never share a temp file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with open(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            self.replace_atomic(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def run_isolation_helper() -> None:
    """Reenter the Linux exec helper when running from a frozen service binary."""
    if sys.platform != "win32" and sys.argv[1:2] == ["--_isolated-exec"]:
        from .linux import exec_isolated_game

        exec_isolated_game(sys.argv[2:])


def check_argv(argv: Sequence[str]) -> list[str]:
    # A joined command line split a profile path with a space on Windows.
    if isinstance(argv, (str, bytes)):
        raise TypeError("argv must be a list of arguments, not a command string")
    return [os.fspath(a) for a in argv]


def current() -> Platform:
    if sys.platform == "win32":
        from .windows import WindowsPlatform

        return WindowsPlatform()
    from .linux import LinuxPlatform

    return LinuxPlatform()
