import fcntl
import os
import signal
import subprocess
from collections.abc import Sequence
from pathlib import Path

from . import InstanceLock, LockHeld, Platform, ProcessTree, check_argv


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


class _FlockLock(InstanceLock):
    def __init__(self, fd: int):
        self._fd: int | None = fd

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)  # closing the last descriptor drops the flock
            self._fd = None


class _GroupTree(ProcessTree):
    def __init__(self, popen: subprocess.Popen):
        self.popen = popen

    def kill(self) -> None:
        try:
            os.killpg(self.popen.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.popen.wait()


class LinuxPlatform(Platform):
    def godot_user_data_root(self) -> Path:
        return _xdg_data_home() / "godot" / "app_userdata"

    def app_data_dir(self) -> Path:
        return _xdg_data_home() / "midgard-farm"

    def acquire_lock(self, path) -> InstanceLock:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise LockHeld(os.fspath(path)) from None
        except BaseException:
            os.close(fd)
            raise
        return _FlockLock(fd)

    def spawn_tree(self, argv: Sequence[str], **popen_kwargs) -> ProcessTree:
        # A new session makes the child the leader of a process group that
        # its descendants inherit, so killpg reaches the grandchildren too.
        return _GroupTree(subprocess.Popen(check_argv(argv), start_new_session=True, **popen_kwargs))

    def replace_atomic(self, src, dst) -> None:
        os.replace(src, dst)
        dir_fd = os.open(Path(dst).parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
