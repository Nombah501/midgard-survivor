"""The platform seam, exercised against the real OS of the runner."""

import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from midgard_farm import platform
from midgard_farm.core.profile import find_profile

from test_profile import godot_root, make_profile

OS = platform.current()


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


def test_game_pids_see_the_game_by_executable_name(tmp_path):
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows v1 policy")
def test_windows_v1_warns_that_afk_network_isolation_is_unavailable():
    warning = OS.check_network_isolation()
    assert warning is not None
    assert "no network isolation" in warning
    assert "updater" in warning and "CloudSave" in warning
