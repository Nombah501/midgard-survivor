import base64
import csv
import ctypes
import msvcrt
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path
from xml.sax.saxutils import escape

from ..core.config import read_config
from . import InstanceLock, LockHeld, NotificationPriority, Platform, ProcessTree, check_argv

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll")

_GODOT_DATA_HOME = "APPDATA"
_GODOT_USER_DATA = Path("Godot", "app_userdata")

SERVICE_TASK_NAME = "Midgard Farm"

_TASK_XML = """\
<?xml version="1.0"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
      <UserId>{sid}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Operator">
      <UserId>{sid}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <Hidden>true</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Operator">
    <Exec>
      <Command>{command}</Command>
{arguments}      <WorkingDirectory>{directory}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33
LOCKFILE_FAIL_IMMEDIATELY = 0x1
LOCKFILE_EXCLUSIVE_LOCK = 0x2
MOVEFILE_REPLACE_EXISTING = 0x1
CREATE_SUSPENDED = 0x4
CREATE_NO_WINDOW = 0x08000000
MOVEFILE_WRITE_THROUGH = 0x8
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# A reader (the window polling a status file) may briefly hold the target open.
REPLACE_RETRY_SECONDS = 2.0

_TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$appId = 'Midgard.Farm'
# The task uses the signed-in user's token: register the identity in that user's hive.
$key = "HKCU:\Software\Classes\AppUserModelId\$appId"
if (-not (Test-Path -LiteralPath $key)) { New-Item -Path $key -Force | Out-Null }
New-ItemProperty -LiteralPath $key -Name DisplayName -PropertyType String -Value 'Midgard Farm' -Force | Out-Null

[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom,ContentType=WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:MIDGARD_FARM_TOAST_XML)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
if ($env:MIDGARD_FARM_TOAST_PRIORITY -eq 'high') { $toast.Priority = 1 }
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId)
$notifier.Show($toast)
"""
_TOAST_COMMAND = base64.b64encode(_TOAST_SCRIPT.encode("utf-16-le")).decode("ascii")


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


class _JOB_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOB_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOB_BASIC_LIMIT_INFORMATION),
        ("IoInfo", ctypes.c_uint64 * 6),  # IO_COUNTERS, reserved by this info class.
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_LockFileEx = _kernel32.LockFileEx
_LockFileEx.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    ctypes.POINTER(_OVERLAPPED),
]
_LockFileEx.restype = wintypes.BOOL
_UnlockFileEx = _kernel32.UnlockFileEx
_UnlockFileEx.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED),
]
_UnlockFileEx.restype = wintypes.BOOL
_MoveFileExW = _kernel32.MoveFileExW
_MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
_MoveFileExW.restype = wintypes.BOOL
_CreateJobObjectW = _kernel32.CreateJobObjectW
_CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
_CreateJobObjectW.restype = wintypes.HANDLE
_SetInformationJobObject = _kernel32.SetInformationJobObject
_SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
_SetInformationJobObject.restype = wintypes.BOOL
_AssignProcessToJobObject = _kernel32.AssignProcessToJobObject
_AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_AssignProcessToJobObject.restype = wintypes.BOOL
_TerminateJobObject = _kernel32.TerminateJobObject
_TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
_TerminateJobObject.restype = wintypes.BOOL
_CloseHandle = _kernel32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]
_CloseHandle.restype = wintypes.BOOL
_OpenProcess = _kernel32.OpenProcess
_OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_OpenProcess.restype = wintypes.HANDLE
_QueryFullProcessImageNameW = _kernel32.QueryFullProcessImageNameW
_QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
]
_QueryFullProcessImageNameW.restype = wintypes.BOOL
_NtResumeProcess = _ntdll.NtResumeProcess
_NtResumeProcess.argtypes = [wintypes.HANDLE]
_NtResumeProcess.restype = ctypes.c_long


def _check(ok) -> None:
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def _env_dir(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"%{name}% is not set")
    return Path(value)


def _system_tool(tool: str, *args: str) -> str:
    command = _env_dir("SystemRoot") / "System32" / tool
    return subprocess.run([str(command), *args], creationflags=CREATE_NO_WINDOW,
                          check=True, capture_output=True, text=True, errors="replace", timeout=15).stdout


def _process_image(pid: int) -> Path | None:
    handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None  # The process may have exited or belong to another user.
    try:
        path = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(path))
        if _QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
            return Path(path.value)
        return None
    finally:
        _CloseHandle(handle)


class _FileLock(InstanceLock):
    def __init__(self, fd: int):
        self._fd: int | None = fd

    def release(self) -> None:
        if self._fd is None:
            return
        _UnlockFileEx(msvcrt.get_osfhandle(self._fd), 0, 1, 0, ctypes.byref(_OVERLAPPED()))
        os.close(self._fd)
        self._fd = None


class _JobTree(ProcessTree):
    def __init__(self, popen: subprocess.Popen, job: int):
        self.popen = popen
        self._job: int | None = job

    def kill(self) -> None:
        if self._job is not None:
            try:
                _check(_TerminateJobObject(self._job, 1))
            finally:
                _CloseHandle(self._job)
                self._job = None
        self.popen.wait()

    def wait(self, timeout: float | None = None) -> int:
        return self.popen.wait(timeout)


class WindowsPlatform(Platform):
    release_os = "windows"
    game_exe_name = "MidgardSurvivors.exe"
    game_exit_status_reliable = False

    def godot_user_data_root(self) -> Path:
        return _env_dir(_GODOT_DATA_HOME) / _GODOT_USER_DATA

    def godot_sandbox(self, data_home: Path) -> tuple[Path, dict[str, str]]:
        return data_home / _GODOT_USER_DATA, {**os.environ, _GODOT_DATA_HOME: str(data_home)}

    def app_sandbox_environment(self, data_home: Path) -> dict[str, str]:
        return self.godot_sandbox(data_home)[1] | {"LOCALAPPDATA": str(data_home)}

    def app_data_dir(self) -> Path:
        return _env_dir("LOCALAPPDATA") / "MidgardFarm"

    def game_executable(self) -> Path:
        if game_dir := os.environ.get("GAME_DIR"):
            return Path(game_dir) / self.game_exe_name
        if configured := read_config(self).game_dir:
            return configured / self.game_exe_name
        if executable := self._known_game() or self._remember_game(self.game_pids()):
            return executable
        raise RuntimeError("start the game once so the app can find it")

    def _game_location_path(self) -> Path:
        return self.app_data_dir() / "game-executable.txt"

    def _known_game(self) -> Path | None:
        try:
            executable = Path(self.read_shared(self._game_location_path()).decode("utf-8"))
        except (OSError, UnicodeError):
            return None
        if self._is_game_executable(executable):
            return executable
        return None

    def _is_game_executable(self, executable: Path) -> bool:
        return (executable.is_absolute() and executable.name.casefold() == self.game_exe_name.casefold()
                and executable.is_file())

    def _remember_game(self, pids: set[int]) -> Path | None:
        for pid in sorted(pids):
            executable = _process_image(pid)
            # The PID may have been reused since tasklist took its snapshot.
            if executable is None or not self._is_game_executable(executable):
                continue
            location = self._game_location_path()
            try:
                location.parent.mkdir(parents=True, exist_ok=True)
                self.write_atomic(location, str(executable).encode("utf-8"))
            except OSError as exc:
                print(f"midgard-farm-service: could not remember game location: {exc}", file=sys.stderr)
            return executable
        return None

    def render_service(self, argv: Sequence[str]) -> str:
        command, *args = check_argv(argv)
        # Use the actual caller's SID, not a possibly ambiguous environment username.
        rows = csv.reader(_system_tool("whoami.exe", "/User", "/FO", "CSV", "/NH").splitlines())
        identity = next(rows, [])
        if len(identity) != 2 or not identity[1].startswith("S-1-"):
            raise RuntimeError("could not identify the current Windows user")
        directory = Path(command).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
        arguments = f"      <Arguments>{escape(subprocess.list2cmdline(args))}</Arguments>\n" if args else ""
        return _TASK_XML.format(sid=escape(identity[1]), command=escape(command),
                                arguments=arguments, directory=escape(str(directory)))

    def register_service(self, argv: Sequence[str]) -> None:
        xml = self.render_service(argv)
        with tempfile.TemporaryDirectory(prefix="midgard-farm-task-") as temporary:
            path = Path(temporary) / "task.xml"
            # schtasks accepts UTF-16LE with a BOM, including non-ASCII paths.
            path.write_text(xml, encoding="utf-16")
            _system_tool("schtasks.exe", "/Create", "/TN", SERVICE_TASK_NAME, "/XML", str(path), "/F")

    def unregister_service(self) -> None:
        _system_tool("schtasks.exe", "/Delete", "/TN", SERVICE_TASK_NAME, "/F")

    def start_service(self) -> None:
        subprocess.run(["schtasks.exe", "/Run", "/TN", SERVICE_TASK_NAME], creationflags=CREATE_NO_WINDOW,
                       check=True, capture_output=True, text=True, errors="replace", timeout=5)

    def notify_desktop(self, title: str, message: str, priority: NotificationPriority) -> None:
        audio = '<audio silent="true"/>' if priority == "low" else ""
        xml = ('<toast><visual><binding template="ToastGeneric">'
               f"<text>{escape(title)}</text><text>{escape(message)}</text>"
               f"</binding></visual>{audio}</toast>")
        powershell = Path(_env_dir("SystemRoot"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand", _TOAST_COMMAND],
                       env={**os.environ, "MIDGARD_FARM_TOAST_XML": xml, "MIDGARD_FARM_TOAST_PRIORITY": priority},
                       creationflags=CREATE_NO_WINDOW, check=True, capture_output=True, timeout=10)

    def game_pids(self) -> set[int]:
        out = _system_tool("tasklist.exe", "/FI", f"IMAGENAME eq {self.game_exe_name}", "/FO", "CSV", "/NH")
        # One `"name","pid",...` row per match; otherwise an "INFO: No tasks" line.
        return {
            int(row[1])
            for row in csv.reader(out.splitlines())
            if len(row) > 1 and row[0].lower() == self.game_exe_name.lower()
        }

    def game_running(self) -> bool:
        pids = self.game_pids()
        if pids and self._known_game() is None:
            self._remember_game(pids)
        return bool(pids)

    def acquire_lock(self, path) -> InstanceLock:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOINHERIT)
        flags = LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY
        if not _LockFileEx(msvcrt.get_osfhandle(fd), flags, 0, 1, 0, ctypes.byref(_OVERLAPPED())):
            err = ctypes.get_last_error()
            os.close(fd)
            if err == ERROR_LOCK_VIOLATION:
                raise LockHeld(os.fspath(path))
            raise ctypes.WinError(err)
        return _FileLock(fd)

    def check_network_isolation(self) -> str:
        return ("Windows v1 has no network isolation: the updater prompt can stall an AFK session "
                "and CloudSave can race a cloud-linked profile.")

    def spawn_tree(self, argv: Sequence[str], *, isolate_network: bool = False, **popen_kwargs) -> ProcessTree:
        # Windows v1 deliberately runs supervised games on the host network.
        # Start suspended so the child joins the Job Object before it can
        # spawn anything; descendants then inherit the job.
        job = _CreateJobObjectW(None, None)
        _check(job)
        flags = popen_kwargs.pop("creationflags", 0) | CREATE_SUSPENDED
        try:
            # The service owns the only handle; a crash must terminate the game too.
            limits = _JOB_EXTENDED_LIMIT_INFORMATION()
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            _check(_SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                            ctypes.byref(limits), ctypes.sizeof(limits)))
            popen = subprocess.Popen(check_argv(argv), creationflags=flags, **popen_kwargs)
        except BaseException:
            _CloseHandle(job)
            raise
        handle = int(popen._handle)  # type: ignore[attr-defined]  # CPython's process handle
        error: OSError | None = None
        if not _AssignProcessToJobObject(job, handle):
            error = ctypes.WinError(ctypes.get_last_error())
        elif (status := _NtResumeProcess(handle)) != 0:
            error = OSError(f"NtResumeProcess failed: NTSTATUS {status & 0xFFFFFFFF:#010x}")
        if error is not None:
            popen.kill()
            popen.wait()
            _CloseHandle(job)
            raise error
        return _JobTree(popen, job)

    def replace_atomic(self, src, dst) -> None:
        flags = MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH
        deadline = time.monotonic() + REPLACE_RETRY_SECONDS
        while not _MoveFileExW(os.fspath(src), os.fspath(dst), flags):
            err = ctypes.get_last_error()
            if err not in (ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION) or time.monotonic() > deadline:
                raise ctypes.WinError(err)
            time.sleep(0.01)

    def read_shared(self, path: Path, *, retry_missing: bool = False) -> bytes:
        deadline = time.monotonic() + 1.0
        while True:
            try:
                return path.read_bytes()
            except (PermissionError, FileNotFoundError) as exc:
                if (isinstance(exc, FileNotFoundError) and not retry_missing) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
