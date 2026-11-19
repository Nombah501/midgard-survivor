"""The platform seam, exercised against the real OS of the runner."""

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from midgard_farm import platform
from midgard_farm.core.profile import find_profile

from test_profile import make_profile

OS = platform.current()


def python(code: str, *args: str, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code), *args],
        stdout=subprocess.PIPE,
        text=True,
        **kwargs,
    )


def test_profile_is_found_under_this_os_godot_root(tmp_path, monkeypatch):
    # Godot's user:// root: $XDG_DATA_HOME/godot/app_userdata on Linux,
    # %APPDATA%\Godot\app_userdata on Windows.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    godot = "Godot" if sys.platform == "win32" else "godot"
    profile = make_profile(tmp_path / godot / "app_userdata", "Ragnarok Survivors")

    assert find_profile(OS.godot_user_data_root()) == profile


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


def counter_stops(path: Path) -> bool:
    """True once the counter at `path` stays unchanged for half a second."""
    before = path.read_text()
    time.sleep(0.5)
    return path.read_text() == before


def test_tree_kill_reaches_grandchildren(tmp_path):
    # The grandchild counts into a file; once the tree is killed it stops.
    beat = tmp_path / "grandchild beat"
    grandchild = textwrap.dedent(
        """
        import sys, time
        n = 0
        while True:
            n += 1
            with open(sys.argv[1], "w") as fh:
                fh.write(str(n))
            time.sleep(0.02)
        """
    )
    child = textwrap.dedent(
        """
        import subprocess, sys, time
        subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2]])
        time.sleep(60)
        """
    )
    tree = OS.spawn_tree([sys.executable, "-c", child, grandchild, str(beat)])
    deadline = time.monotonic() + 10
    while not beat.exists() or not beat.read_text():
        assert time.monotonic() < deadline, "grandchild never started"
        time.sleep(0.02)
    assert not counter_stops(beat)

    tree.kill()

    assert tree.popen.returncode is not None
    assert counter_stops(beat)


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
        for i in range(100):
            os_.write_atomic(sys.argv[1], (b"b" * 2_000_000) if i % 2 == 0 else (b"a" * 1_000_000))
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
    assert seen <= {old, new}
    assert target.read_bytes() == old
    assert [p.name for p in tmp_path.iterdir()] == [target.name]
