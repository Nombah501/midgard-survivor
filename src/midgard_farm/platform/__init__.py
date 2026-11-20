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

    executable_suffix = ""

    game_exe_name: str
    """File name of the game executable on this OS."""

    @abc.abstractmethod
    def godot_user_data_root(self) -> Path:
        """Godot's root for `user://` folders of apps without a custom user dir."""

    @abc.abstractmethod
    def godot_sandbox(self, data_home: Path) -> tuple[Path, dict[str, str]]:
        """Return the Godot user-data root and child environment for an isolated data home."""

    def app_sandbox_environment(self, data_home: Path) -> dict[str, str]:
        """Child environment redirecting both Godot user data and this app's storage."""
        return self.godot_sandbox(data_home)[1]

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
    def game_executable(self) -> Path:
        """Resolve the installed game executable, honoring per-user overrides."""

    @abc.abstractmethod
    def game_pids(self) -> set[int]:
        """Processes running the game executable, from any folder."""

    def game_running(self) -> bool:
        return bool(self.game_pids())

    def kill_owned_sandbox_game(self, pid: int, data_home: Path, session: str) -> bool:
        """Kill only a matching game child launched in the given verification sandbox."""
        raise NotImplementedError("external sandbox game kill is unsupported on this OS")

    def process_rss_kib(self, pid: int) -> int | None:
        """Resident size in KiB; None if the process has exited or has no reading."""
        raise NotImplementedError("RSS sampling is unsupported on this OS")

    def allocated_bytes(self, path: Path) -> int:
        """Disk blocks allocated to a file; its logical size on Windows."""
        return path.stat().st_size

    @abc.abstractmethod
    def render_service(self, argv: Sequence[str]) -> str:
        """Render this user's service definition without installing it."""

    @abc.abstractmethod
    def register_service(self, argv: Sequence[str]) -> None:
        """Install or replace the background service without starting it."""

    @abc.abstractmethod
    def unregister_service(self) -> None:
        """Stop and remove the background service registration."""

    @abc.abstractmethod
    def start_service(self) -> None:
        """Ask the OS to start the registered Midgard Farm background service."""

    @abc.abstractmethod
    def queue_update_watchdog(self, argv: Sequence[str]) -> None:
        """Queue an on-demand process independent of the running service's lifetime."""

    @abc.abstractmethod
    def restart_service(self) -> None:
        """Ask the registered launcher to restart, from the independent watchdog."""

    def service_start_refused(self) -> bool:
        """Whether the scheduler definitively refused startup, not a service exit."""
        return False

    def clear_update_watchdog(self) -> None:
        """Remove any registration left behind by the one-shot watchdog."""

    @abc.abstractmethod
    def run_service_binary(self, argv: Sequence[str]) -> int:
        """Run the selected service under the registered launcher."""

    def setup_warnings(self) -> tuple[str, ...]:
        """Read settings that may prevent an unattended night."""
        return ()

    def report_launcher_error(self, message: str) -> None:
        print(message, file=sys.stderr)

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
