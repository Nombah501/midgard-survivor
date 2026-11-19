import fcntl
import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Never

from . import InstanceLock, LockHeld, NetworkIsolationError, NotificationPriority, Platform, ProcessTree, check_argv

_GODOT_DATA_HOME = "XDG_DATA_HOME"
_GODOT_USER_DATA = Path("godot", "app_userdata")


def _xdg_data_home() -> Path:
    return Path(os.environ.get(_GODOT_DATA_HOME) or Path.home() / ".local" / "share")


def exec_isolated_game(args: list[str]) -> Never:
    """Prove namespace entry over a private pipe, then exec without a shell."""
    fd, outer_netns, *argv = args
    if os.readlink("/proc/self/ns/net") == outer_netns:
        raise SystemExit("network namespace did not change")
    os.write(int(fd), b"1")
    os.close(int(fd))
    os.execv(argv[0], argv)


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
        self._killed = False

    def kill(self) -> None:
        if not self._killed:
            # The group outlives its leader while any descendant is alive.
            try:
                os.killpg(self.popen.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self._killed = True
        self.popen.wait()

    def wait(self, timeout: float | None = None) -> int:
        return self.popen.wait(timeout)


class LinuxPlatform(Platform):
    release_os = "linux"
    game_exe_name = "MidgardSurvivors.x86_64"
    game_exit_status_reliable = True

    def godot_user_data_root(self) -> Path:
        return _xdg_data_home() / _GODOT_USER_DATA

    def godot_sandbox(self, data_home: Path) -> tuple[Path, dict[str, str]]:
        return data_home / _GODOT_USER_DATA, {**os.environ, _GODOT_DATA_HOME: str(data_home)}

    def app_data_dir(self) -> Path:
        return _xdg_data_home() / "midgard-farm"

    def default_game_dir(self) -> Path:
        return Path.home() / "games" / "midgard-survivors"

    def start_service(self) -> None:
        subprocess.run(["systemctl", "--user", "start", "midgard-farm.service"],
                       check=True, capture_output=True, text=True, errors="replace", timeout=5)

    def notify_desktop(self, title: str, message: str, priority: NotificationPriority) -> None:
        urgency = "critical" if priority == "high" else priority
        subprocess.run(["notify-send", "--app-name=Midgard Farm", f"--urgency={urgency}", "--", title, message],
                       check=True, capture_output=True, timeout=10)

    def game_pids(self) -> set[int]:
        # The argv[0] name, as `pgrep -f` matched in run.sh: `unshare` execs
        # the game, so an isolated game shows its own path there.
        pids = set()
        for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
            try:
                argv0 = cmdline.read_bytes().split(b"\0", 1)[0]
            except OSError:  # exited meanwhile, or not ours to read
                continue
            if os.path.basename(os.fsdecode(argv0)) == self.game_exe_name:
                pids.add(int(cmdline.parent.name))
        return pids

    def kill_owned_sandbox_game(self, pid: int, data_home: Path, session: str) -> bool:
        if pid <= 1 or not session.startswith("verify-"):
            return False
        # Pin the PID against reuse; status files alone do not establish ownership.
        try:
            fd = os.pidfd_open(pid)
        except ProcessLookupError:
            return False
        try:
            proc = Path(f"/proc/{pid}")
            ppid = next(line for line in (proc / "status").read_bytes().splitlines() if line.startswith(b"PPid:"))
            if int(ppid.split()[1]) != os.getpid() or pid not in self.game_pids():
                return False
            child_env = (proc / "environ").read_bytes().split(b"\0")
            if (os.fsencode(_GODOT_DATA_HOME + "=") + os.fsencode(data_home) not in child_env
                    or b"FARMER_SESSION_ID=" + session.encode() not in child_env):
                return False
            signal.pidfd_send_signal(fd, signal.SIGKILL)
            return True
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            return False
        finally:
            os.close(fd)

    def process_rss_kib(self, pid: int) -> int | None:
        try:
            with Path(f"/proc/{pid}/status").open() as status:
                for line in status:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
        except (OSError, ValueError):
            pass
        return None

    def allocated_bytes(self, path: Path) -> int:
        return path.stat().st_blocks * 512

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

    def check_network_isolation(self) -> None:
        try:
            subprocess.run(["unshare", "-cn", "--", "true"], capture_output=True, check=True)
        except (FileNotFoundError, PermissionError, subprocess.CalledProcessError) as exc:
            detail = (
                exc.stderr.decode(errors="replace").strip()
                if isinstance(exc, subprocess.CalledProcessError) else str(exc)
            )
            raise NetworkIsolationError(
                "network isolation requires util-linux unshare -cn and permission to create user/network namespaces"
                f"; no game launched: {detail}"
            ) from exc

    def spawn_tree(self, argv: Sequence[str], *, isolate_network: bool = False, **popen_kwargs) -> ProcessTree:
        command = check_argv(argv)
        if not isolate_network:
            return _GroupTree(subprocess.Popen(command, start_new_session=True, **popen_kwargs))
        # unshare execs the helper, which execs the game in the same killable group.
        helper = [sys.executable, "--_isolated-exec"] if getattr(sys, "frozen", False) else [
            sys.executable, "-m", "midgard_farm.platform.linux",
        ]
        outer_netns = os.readlink("/proc/self/ns/net")
        reader, writer = os.pipe()
        try:
            try:
                tree = _GroupTree(subprocess.Popen(
                    ["unshare", "-cn", "--", *helper, str(writer), outer_netns, *command],
                    start_new_session=True, pass_fds=(writer,), **popen_kwargs,
                ))
            except (FileNotFoundError, PermissionError) as exc:
                raise NetworkIsolationError(f"network isolation could not start unshare: {exc}") from exc
            finally:
                os.close(writer)
            try:
                if os.read(reader, 1) != b"1":
                    raise NetworkIsolationError("network isolation failed before the supervised game could launch")
            except BaseException:
                tree.kill()
                raise
            return tree
        finally:
            os.close(reader)

    def replace_atomic(self, src, dst) -> None:
        os.replace(src, dst)
        dir_fd = os.open(Path(dst).parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


if __name__ == "__main__":
    exec_isolated_game(sys.argv[1:])
