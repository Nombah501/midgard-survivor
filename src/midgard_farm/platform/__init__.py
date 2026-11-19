"""Everything that differs between Linux and Windows, behind one interface.

The core asks `current()` for the implementation and never branches on the OS.
"""

import abc
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path


class LockHeld(Exception):
    """Another process holds the single-instance lock."""


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
    game_exe_name: str
    """File name of the game executable on this OS."""

    @abc.abstractmethod
    def godot_user_data_root(self) -> Path:
        """Godot's root for `user://` folders of apps without a custom user dir."""

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
    def acquire_lock(self, path: str | os.PathLike) -> InstanceLock:
        """Take the exclusive lock on `path` without waiting; raise LockHeld if taken."""

    @abc.abstractmethod
    def spawn_tree(self, argv: Sequence[str], **popen_kwargs) -> ProcessTree:
        """Start `argv` in a group that `ProcessTree.kill` ends as a whole."""

    @abc.abstractmethod
    def replace_atomic(self, src: str | os.PathLike, dst: str | os.PathLike) -> None:
        """Replace `dst` with `src` in a single OS operation, durably."""

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
