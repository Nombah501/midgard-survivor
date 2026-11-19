"""The platform seam, exercised against the real OS of the runner."""

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
