"""The platform seam, exercised against the real OS of the runner."""

import base64
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path
from xml.etree import ElementTree

import pytest

from midgard_farm import platform
from midgard_farm.core.profile import find_profile

from test_profile import godot_root, make_profile

OS = platform.current()
WINDOWS_CI = sys.platform == "win32" and os.environ.get("GITHUB_ACTIONS") == "true"
TASK_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def python(code: str, *args: str, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code), *args],
        stdout=subprocess.PIPE,
        text=True,
        **kwargs,
    )


def test_profile_is_found_under_this_os_godot_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    profile = make_profile(godot_root(tmp_path), "Ragnarok Survivors")

    assert find_profile(OS.godot_user_data_root()) == profile


def test_godot_sandbox_paths_apply_only_to_the_child(tmp_path, monkeypatch):
    real = tmp_path / "real data"
    for name in ("XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(real))
    sandbox = tmp_path / "sandbox data"

    root, env = OS.godot_sandbox(sandbox)
    expected = make_profile(godot_root(sandbox), "Renamed Game Profile")
    with python(
        """
        from midgard_farm import platform
        from midgard_farm.core.profile import find_profile
        print(find_profile(platform.current().godot_user_data_root()))
        """,
        env=env,
    ) as child:
        stdout, _ = child.communicate(timeout=30)

    assert child.returncode == 0
    assert Path(stdout.strip()) == expected
    assert root == godot_root(sandbox)
    assert OS.godot_user_data_root() == godot_root(real)


def test_sandbox_pack_link_shares_the_pack_and_can_be_removed(tmp_path):
    pack = tmp_path / "official.pck"
    pack.write_bytes(b"official pack")
    link = tmp_path / "sandbox.pck"
    OS.link_sandbox_pack(pack, link)

    assert pack.samefile(link)
    link.unlink()
    assert pack.read_bytes() == b"official pack"


def test_lock_is_exclusive_across_processes_and_freed_when_holder_dies(tmp_path):
    lock_path = tmp_path / "service.lock"
    holder = python(
        """
        import sys, time
        from midgard_farm import platform
        lock = platform.current().acquire_lock(sys.argv[1])
        print("held", flush=True)
        time.sleep(60)
        """,
        str(lock_path),
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(platform.LockHeld):
            OS.acquire_lock(lock_path)
    finally:
        holder.kill()
        holder.wait()
        holder.stdout.close()

    with OS.acquire_lock(lock_path):
        with pytest.raises(platform.LockHeld):
            OS.acquire_lock(lock_path)
    OS.acquire_lock(lock_path).release()


def lock_freed_within(path: Path, seconds: float) -> bool:
    """True once the lock at `path` can be taken, i.e. its holder has died."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            OS.acquire_lock(path).release()
            return True
        except platform.LockHeld:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.05)


def test_tree_kill_reaches_grandchildren(tmp_path):
    # The grandchild holds a lock; the OS frees it only when the grandchild dies.
    lock_path = tmp_path / "grandchild lock"
    ready = tmp_path / "grandchild ready"
    grandchild = textwrap.dedent(
        """
        import sys, time
        from midgard_farm import platform
        lock = platform.current().acquire_lock(sys.argv[1])
        open(sys.argv[2], "w").close()
        time.sleep(60)
        """
    )
    child = textwrap.dedent(
        """
        import subprocess, sys, time
        subprocess.Popen([sys.executable, "-c", *sys.argv[1:]])
        time.sleep(60)
        """
    )
    with OS.spawn_tree([sys.executable, "-c", child, grandchild, str(lock_path), str(ready)]) as tree:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert time.monotonic() < deadline, "grandchild never started"
            time.sleep(0.02)
        with pytest.raises(platform.LockHeld):
            OS.acquire_lock(lock_path)

        tree.kill()

        assert tree.popen.returncode is not None
        assert lock_freed_within(lock_path, 5), "grandchild survived the tree kill"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object kill-on-close")
def test_job_owner_crash_kills_the_root_and_grandchild(tmp_path):
    ready = tmp_path / "grandchild-ready"
    root_lock = tmp_path / "root-lock"
    grandchild_lock = tmp_path / "grandchild-lock"
    child = textwrap.dedent("""
        import subprocess, sys, time
        from pathlib import Path
        from midgard_farm import platform
        mode, path, ready, *rest = sys.argv[1:]
        lock = platform.current().acquire_lock(path)
        if mode == "root":
            subprocess.Popen([sys.executable, "-c", rest[0], "leaf", rest[1], ready])
        else:
            Path(ready).touch()
        time.sleep(60)
    """)
    with python("""
        import sys, time
        from midgard_farm import platform
        child, root_lock, grandchild_lock, ready = sys.argv[1:]
        tree = platform.current().spawn_tree(
            [sys.executable, "-c", child, "root", root_lock, ready, child, grandchild_lock]
        )
        time.sleep(60)
    """, child, str(root_lock), str(grandchild_lock), str(ready)) as owner:
        try:
            deadline = time.monotonic() + 10
            while not ready.exists():
                assert time.monotonic() < deadline, "grandchild never started"
                time.sleep(0.02)
            for lock in (root_lock, grandchild_lock):
                with pytest.raises(platform.LockHeld):
                    OS.acquire_lock(lock)
        finally:
            # TerminateProcess: no Python context manager or normal cleanup can run.
            owner.kill()
            owner.wait(timeout=5)
            owner.stdout.close()
        for lock in (root_lock, grandchild_lock):
            assert lock_freed_within(lock, 5), f"{lock.name} survived the job owner"


def test_a_tree_that_exits_on_its_own_reports_its_code():
    with OS.spawn_tree([sys.executable, "-c", "raise SystemExit(7)"]) as tree:
        assert tree.wait(timeout=30) == 7


def test_spawn_refuses_a_command_string():
    with pytest.raises(TypeError):
        OS.spawn_tree(f'"{sys.executable}" -c pass')


def test_readers_see_old_or_new_content_never_a_mix(tmp_path):
    target = tmp_path / "farmer status.json"
    old, new = b"a" * 1_000_000, b"b" * 2_000_000
    OS.write_atomic(target, old)
    writer = python(
        """
        import sys
        from midgard_farm import platform
        os_ = platform.current()
        for i in range(50):
            os_.write_atomic(sys.argv[1], b"b" * 2_000_000)
            os_.write_atomic(sys.argv[1], b"a" * 1_000_000)
        """,
        str(target),
    )
    seen = set()
    while writer.poll() is None:
        try:
            seen.add(target.read_bytes())
        except PermissionError:
            continue  # Windows: the name is briefly pending replacement
    assert writer.wait() == 0
    writer.stdout.close()
    assert seen == {old, new}
    assert target.read_bytes() == old
    assert [p.name for p in tmp_path.iterdir()] == [target.name]


def test_shared_reads_while_writer_replaces_the_file(tmp_path):
    target = tmp_path / "service state.json"
    old, new = b"idle\n", b"active\n"
    OS.write_atomic(target, old)
    writer = python(
        """
        import sys, time
        from midgard_farm import platform
        os_ = platform.current()
        for i in range(200):
            os_.write_atomic(sys.argv[1], b"active\\n" if i % 2 == 0 else b"idle\\n")
            if i < 2:
                time.sleep(0.05)
        """,
        str(target),
    )
    seen = set()
    try:
        while writer.poll() is None:
            seen.add(OS.read_shared(target))
            time.sleep(0.001)
        assert writer.wait() == 0
        assert seen == {old, new}
    finally:
        if writer.poll() is None:
            writer.kill()
            writer.wait()
        writer.stdout.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing violation")
def test_shared_read_retries_an_exclusive_windows_open(tmp_path):
    import ctypes
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from ctypes import wintypes

    target = tmp_path / "quarantine.json"
    target.write_bytes(b"quarantine")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    open_file = kernel.CreateFileW
    open_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                          wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    open_file.restype = wintypes.HANDLE
    close_file = kernel.CloseHandle
    close_file.argtypes = [wintypes.HANDLE]
    close_file.restype = wintypes.BOOL
    with ThreadPoolExecutor(max_workers=1) as pool:
        handle = open_file(str(target), 0x80000000, 0, None, 3, 0, None)  # GENERIC_READ, OPEN_EXISTING
        assert handle and handle != ctypes.c_void_p(-1).value
        try:
            reading = pool.submit(OS.read_shared, target)
            with pytest.raises(TimeoutError):
                reading.result(timeout=0.1)
        finally:
            assert close_file(handle)
        assert reading.result(timeout=1) == b"quarantine"


def fake_game(tmp_path: Path) -> list[str]:
    """A long-running command whose executable has the game's file name."""
    exe = tmp_path / "game dir" / OS.game_exe_name
    exe.parent.mkdir()
    if sys.platform == "win32":
        # A standalone system tool keeps working under another name.
        shutil.copy(Path(os.environ["SystemRoot"]) / "System32" / "PING.EXE", exe)
        return [str(exe), "-n", "60", "127.0.0.1"]
    exe.symlink_to(os.path.realpath(sys.executable))
    return [str(exe), "-c", "import time; time.sleep(60)"]


def test_game_pids_see_the_game_by_executable_name(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # By pid: the operator's real game may be running on this machine.
    with OS.spawn_tree(fake_game(tmp_path), stdout=subprocess.DEVNULL) as game:
        deadline = time.monotonic() + 10
        while game.popen.pid not in OS.game_pids():
            assert time.monotonic() < deadline, "running game not seen"
            time.sleep(0.05)
        assert OS.game_running()
        game.kill()
        assert game.popen.pid not in OS.game_pids()


def test_game_executable_follows_game_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_DIR", str(tmp_path / "Midgard Survivors"))

    assert OS.game_executable() == tmp_path / "Midgard Survivors" / OS.game_exe_name


@pytest.mark.skipif(sys.platform != "win32", reason="Windows game discovery")
def test_windows_preflight_explains_an_unknown_game_location(tmp_path, monkeypatch):
    from midgard_farm.core.preflight import PreflightError, check_prerequisites

    monkeypatch.delenv("GAME_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    monkeypatch.setattr(os_, "game_pids", set)  # The operator could have a real game running.
    with pytest.raises(PreflightError, match="start the game once so the app can find it"):
        check_prerequisites(os_, tmp_path / "unused profile")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows game discovery")
def test_windows_remembers_the_running_executable_across_service_restarts(tmp_path, monkeypatch):
    monkeypatch.delenv("GAME_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    argv = fake_game(tmp_path)
    exe = Path(argv[0])
    with OS.spawn_tree(argv, stdout=subprocess.DEVNULL) as game:
        # Query a real fake-game PID, but never learn any other running game's location.
        monkeypatch.setattr(OS, "game_pids", lambda: {game.popen.pid})
        assert OS.game_running()

    os_ = platform.current()
    monkeypatch.setattr(os_, "game_pids", set)
    assert os_.game_executable() == exe
    configured = tmp_path / "configured game"
    config = os_.app_data_dir() / "config.json"
    config.write_text(json.dumps({"game_dir": str(configured)}), encoding="utf-8")
    assert os_.game_executable() == configured / OS.game_exe_name
    env_override = tmp_path / "env game"
    monkeypatch.setenv("GAME_DIR", str(env_override))
    assert os_.game_executable() == env_override / OS.game_exe_name


@pytest.mark.skipif(sys.platform != "win32", reason="Windows v1 policy")
def test_windows_v1_warns_that_afk_network_isolation_is_unavailable():
    warning = OS.check_network_isolation()
    assert warning is not None
    assert "no network isolation" in warning
    assert "updater" in warning and "CloudSave" in warning


def test_app_sandbox_environment_redirects_profile_and_app_storage(tmp_path):
    with python(
        """
        from midgard_farm import platform
        os_ = platform.current()
        print(os_.godot_user_data_root())
        print(os_.app_data_dir())
        """,
        env=OS.app_sandbox_environment(tmp_path),
    ) as child:
        stdout, _ = child.communicate(timeout=30)
    assert child.returncode == 0
    godot, data = map(Path, stdout.splitlines())
    assert godot == godot_root(tmp_path)
    assert data.is_relative_to(tmp_path)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux allocated disk usage and RSS")
def test_soak_platform_metrics_use_allocated_blocks_and_resident_memory(tmp_path):
    sparse = tmp_path / "sparse.log"
    with sparse.open("wb") as file:
        file.seek(1024 * 1024)
        file.write(b"a")
    assert OS.allocated_bytes(sparse) == sparse.stat().st_blocks * 512
    assert OS.process_rss_kib(os.getpid()) > 0


@pytest.mark.skipif(sys.platform != "linux", reason="Linux pidfd sandbox fault")
def test_sandbox_kill_pins_a_child_and_checks_its_home_and_session(tmp_path):
    class TestPlatform(type(OS)):
        game_exe_name = "midgard-verify-process-fixture"

    os_ = TestPlatform()
    exe = tmp_path / os_.game_exe_name
    exe.symlink_to(Path(sys.executable).resolve())
    env = os_.app_sandbox_environment(tmp_path)
    session = "verify-example"
    env["FARMER_SESSION_ID"] = session
    with os_.spawn_tree([str(exe), "-c", "import time; time.sleep(60)"], env=env) as tree:
        pid = tree.popen.pid
        assert not os_.kill_owned_sandbox_game(os.getpid(), tmp_path, session)
        assert not os_.kill_owned_sandbox_game(pid, tmp_path / "wrong-home", session)
        assert not os_.kill_owned_sandbox_game(pid, tmp_path, "verify-other")
        assert tree.popen.poll() is None
        assert os_.kill_owned_sandbox_game(pid, tmp_path, session)
        assert tree.wait(timeout=5) == -9


@pytest.mark.skipif(sys.platform != "linux", reason="systemd user registration")
def test_service_registration_writes_and_removes_the_user_unit(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    calls = []

    def systemctl(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", systemctl)
    argv = ["/opt/Midgard Farm/python", "-m", "midgard_farm.service"]
    unit = tmp_path / "systemd" / "user" / "midgard-farm.service"
    rendered = OS.render_service(argv)
    assert 'ExecStart="/opt/Midgard Farm/python" "-m" "midgard_farm.service"' in rendered
    assert "Restart=on-failure\n" in rendered
    assert not unit.exists() and not calls

    OS.register_service(argv)
    assert unit.read_text(encoding="utf-8") == rendered
    OS.unregister_service()
    assert not unit.exists()
    assert calls == [["systemctl", "--user", "daemon-reload"]] * 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Task Scheduler")
def test_windows_task_xml_and_registration_commands(tmp_path, monkeypatch):
    sid = "S-1-5-21-123-456-789-1001"
    calls = []
    registered = []

    def run(argv, **kwargs):
        tool = Path(argv[0]).name.lower()
        if tool == "whoami.exe":
            return subprocess.CompletedProcess(argv, 0, stdout=f'"PC\\user","{sid}"\r\n')
        assert tool == "schtasks.exe"
        calls.append(argv[1:])
        assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        if argv[1] == "/Create":
            registered.append(Path(argv[argv.index("/XML") + 1]).read_text(encoding="utf-16"))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    executable = str(tmp_path / "Мидгард & Farm" / "pythonw.exe")
    argv = [executable, "-m", "midgard_farm.service", "some & arg"]
    text = OS.render_service(argv)
    assert not calls
    task = ElementTree.fromstring(text)
    expected = {
        "t:Triggers/t:LogonTrigger/t:UserId": sid,
        "t:Triggers/t:LogonTrigger/t:ExecutionTimeLimit": "PT0S",
        "t:Principals/t:Principal/t:UserId": sid,
        "t:Principals/t:Principal/t:LogonType": "InteractiveToken",
        "t:Principals/t:Principal/t:RunLevel": "LeastPrivilege",
        "t:Settings/t:Hidden": "true",
        "t:Settings/t:RestartOnFailure/t:Count": "3",
        "t:Settings/t:RestartOnFailure/t:Interval": "PT1M",
        "t:Settings/t:ExecutionTimeLimit": "PT0S",
        "t:Settings/t:MultipleInstancesPolicy": "IgnoreNew",
        "t:Settings/t:DisallowStartIfOnBatteries": "false",
        "t:Settings/t:StopIfGoingOnBatteries": "false",
        "t:Actions/t:Exec/t:Command": executable,
        "t:Actions/t:Exec/t:Arguments": '-m midgard_farm.service "some & arg"',
    }
    for selector, value in expected.items():
        assert task.findtext(selector, namespaces=TASK_NS) == value

    OS.register_service(argv)
    OS.start_service()
    OS.unregister_service()
    assert registered == [text]
    assert calls[0][:4] == ["/Create", "/TN", "Midgard Farm", "/XML"]
    assert calls[0][5:] == ["/F"]
    assert not Path(calls[0][4]).exists()
    assert calls[1:] == [["/Run", "/TN", "Midgard Farm"], ["/Delete", "/TN", "Midgard Farm", "/F"]]


@pytest.mark.skipif(not WINDOWS_CI, reason="real Task Scheduler round trip on Windows CI only")
def test_windows_scheduler_accepts_and_deletes_the_task(monkeypatch):
    from midgard_farm.platform import windows

    task_name = f"Midgard Farm CI {uuid.uuid4().hex}"
    monkeypatch.setattr(windows, "SERVICE_TASK_NAME", task_name)
    query = ["schtasks.exe", "/Query", "/TN", task_name, "/XML"]
    argv = [sys.executable, "-c", "pass"]
    try:
        OS.register_service(argv)
        result = subprocess.run(query, check=True, capture_output=True, timeout=20)
        # `schtasks /Query /XML` emits UTF-16 (unlike regular console queries).
        xml = result.stdout
        if xml.startswith(b"\xff\xfe") or b"\0" in xml[:8]:
            xml = xml.decode("utf-16-le").lstrip("\ufeff").encode("utf-8")
        root = ElementTree.fromstring(xml.decode("utf-8").strip())
        assert root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=TASK_NS) == "-c pass"
        assert root.findtext("t:Settings/t:Hidden", namespaces=TASK_NS) == "true"
    finally:
        # A failed registration must not replace its useful error with a missing-task error.
        if subprocess.run(query, capture_output=True, timeout=20).returncode == 0:
            OS.unregister_service()
    assert subprocess.run(query, capture_output=True, timeout=20).returncode != 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows desktop notifications")
def test_windows_toast_arguments_are_windowless_and_escape_xml(monkeypatch):
    def run(argv, **kwargs):
        assert Path(argv[0]).name == "powershell.exe"
        assert argv[1:4] == ["-NoProfile", "-NonInteractive", "-EncodedCommand"]
        assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kwargs["timeout"] == 10
        env = kwargs["env"]
        xml = ElementTree.fromstring(env["MIDGARD_FARM_TOAST_XML"])
        assert [node.text for node in xml.findall(".//text")] == ["Test & title", "<message>"]
        assert xml.find("audio").get("silent") == "true"
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", run)
    OS.notify_desktop("Test & title", "<message>", "low")


@pytest.mark.skipif(not WINDOWS_CI, reason="real PowerShell parser on Windows CI only")
def test_windows_toast_script_parses_without_showing_a_toast(monkeypatch):
    run = subprocess.run

    def parse_only(argv, **kwargs):
        wrapper = b64_powershell("""
            $tokens = $null; $errors = $null
            $source = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($env:TOAST_UNDER_TEST))
            [System.Management.Automation.Language.Parser]::ParseInput(
                $source, [ref]$tokens, [ref]$errors) | Out-Null
            if ($errors.Count -ne 0) { $errors | Out-String | Write-Error; exit 1 }
            exit 0
        """)
        result = run([*argv[:-1], wrapper], **(kwargs | {"check": False, "env": kwargs["env"] | {
            "TOAST_UNDER_TEST": argv[-1],
        }}))
        assert result.returncode == 0, result.stderr
        return result

    monkeypatch.setattr(subprocess, "run", parse_only)
    OS.notify_desktop("Parser only", "No notification is displayed", "high")


def b64_powershell(code: str) -> str:
    return base64.b64encode(textwrap.dedent(code).encode("utf-16-le")).decode("ascii")
