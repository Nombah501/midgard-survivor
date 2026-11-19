import base64
import csv
import ctypes
import msvcrt
import os
import subprocess
import time
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path
from xml.sax.saxutils import escape

from . import InstanceLock, LockHeld, NotificationPriority, Platform, ProcessTree, check_argv

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ntdll = ctypes.WinDLL("ntdll")

_GODOT_DATA_HOME = "APPDATA"
_GODOT_USER_DATA = Path("Godot", "app_userdata")

SERVICE_TASK_NAME = "Midgard Farm"

ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33
LOCKFILE_FAIL_IMMEDIATELY = 0x1
LOCKFILE_EXCLUSIVE_LOCK = 0x2
MOVEFILE_REPLACE_EXISTING = 0x1
CREATE_SUSPENDED = 0x4
CREATE_NO_WINDOW = 0x08000000
MOVEFILE_WRITE_THROUGH = 0x8
# A reader (the window polling a status file) may briefly hold the target open.
REPLACE_RETRY_SECONDS = 2.0

_TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$appId = 'Midgard.Farm'
# A per-user identity needs no desktop window, shortcut target or administrator.
$key = "HKCU:\Software\Classes\AppUserModelId\$appId"
if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }
New-ItemProperty -Path $key -Name DisplayName -Value 'Midgard Farm' -Force | Out-Null

[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom,ContentType=WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($env:MIDGARD_FARM_TOAST_XML)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
if ($env:MIDGARD_FARM_TOAST_PRIORITY -eq 'high') { $toast.Priority = 1 }
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
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
_AssignProcessToJobObject = _kernel32.AssignProcessToJobObject
_AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
_AssignProcessToJobObject.restype = wintypes.BOOL
_TerminateJobObject = _kernel32.TerminateJobObject
_TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
_TerminateJobObject.restype = wintypes.BOOL
_CloseHandle = _kernel32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]
_CloseHandle.restype = wintypes.BOOL
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
            _check(_TerminateJobObject(self._job, 1))
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

    def app_data_dir(self) -> Path:
        return _env_dir("LOCALAPPDATA") / "MidgardFarm"

    def default_game_dir(self) -> Path:
        # The game ships as a ZIP unpacked anywhere; no install location to assume.
        raise RuntimeError("the game folder is unknown on Windows; set GAME_DIR")

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
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {self.game_exe_name}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, check=True, creationflags=CREATE_NO_WINDOW,
        ).stdout
        # One `"name","pid",...` row per match; otherwise an "INFO: No tasks" line.
        return {
            int(row[1])
            for row in csv.reader(out.splitlines())
            if len(row) > 1 and row[0].lower() == self.game_exe_name.lower()
        }

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
