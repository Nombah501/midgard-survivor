"""Exercise the service CLI with a fake game and a temporary profile/install."""

import hashlib
import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from midgard_farm import platform
from midgard_farm.core import patch_info
from midgard_farm.core.backup import known_good_snapshot, publish_known_good

from test_profile import godot_root, make_profile

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux launcher parity")

PROFILE = b"\x00\xffopaque Godot profile\x80"
COMPANION = b"\x00\x81previous profile"


@dataclass
class Launcher:
    os_: platform.Platform
    profile: Path
    game: Path

    @property
    def data(self):
        return self.os_.app_data_dir()

    @property
    def command(self):
        return [sys.executable, "-m", "midgard_farm.service", "launch"]

    def run(self, code=0, *args, mode="done", **kwargs):
        proc = subprocess.run(
            [*self.command, *args], env={**os.environ, "FAKE_GAME_MODE": mode},
            capture_output=True, encoding="utf-8", timeout=10, **kwargs,
        )
        assert proc.returncode == code, proc.stdout + proc.stderr
        return proc

    def record(self):
        return json.loads((self.profile / "fake-game.json").read_text())


@pytest.fixture
def launcher(tmp_path, monkeypatch, service_game_platform):
    os_, _ = service_game_platform
    home = tmp_path / "xdg"
    game_dir = tmp_path / "game install"
    for name in ("FARMER_SESSION_ID", "FARMER_BACKUP_DIR", "FARMER_DISPLAY", "FARMER_MIN_FREE_MB",
                 "FAKE_GAME_FINISH_REASON"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    monkeypatch.setenv("GAME_DIR", str(game_dir))
    profile = make_profile(godot_root(home), "Renamed Midgard Survivors")
    monkeypatch.setenv("FAKE_GAME_PROFILE", str(profile))
    (profile / "profile.json").write_bytes(PROFILE)
    (profile / "profile.bak.json").write_bytes(COMPANION)
    (profile / "farmer.cfg").write_text("{}")
    (profile / "patches/state.json").write_text('{"file":"patch_farmer.pck"}')
    (profile / "patches/patch_official.pck").write_bytes(b"official")
    (profile / "patches/patch_farmer.pck").write_bytes(b"farmer")
    patch_info.save(os_, patch_info.info_path(os_), patch_info.PatchInfo(
        patch_file="patch_official.pck", patch_version="1", patch_sha256=hashlib.sha256(b"official").hexdigest(),
        bridge_file="bridge.pck", bridge_sha256="", bytecode="ebc36a7", farmer_api=1,
        farmer_hash="fixture", result_sha256=hashlib.sha256(b"farmer").hexdigest(),
        built_at="2026-01-01T00:00:00+00:00",
    ))
    game_dir.mkdir()
    game = os_.game_executable()
    game.write_bytes(f"#!{sys.executable}\n".encode() + Path(__file__).with_name("fake_launch_game.py").read_bytes())
    game.chmod(0o755)
    return Launcher(os_, profile, game)


def test_manual_launch_uses_preset_keeps_network_and_preserves_spaced_paths(launcher, monkeypatch):
    preset = launcher.profile / "my preset.json"
    preset.write_text('{"speed": 10}')
    bin_dir = launcher.data / "empty PATH"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))  # unshare unavailable

    launcher.run(0, str(preset))

    record = launcher.record()
    assert record["netns"] == os.readlink("/proc/self/ns/net")
    assert record["interfaces"] == sorted(name for _, name in socket.if_nameindex())
    assert record["args"] == ["--headless"]
    assert record["cwd"] == str(launcher.game.parent)
    assert record["session"] == "1"
    assert record["config"] == {"speed": 10}
    assert not (launcher.data / "backups/known-good").exists()


@pytest.fixture
def supervised(launcher, monkeypatch):
    if shutil.which("unshare") is None:
        pytest.skip("util-linux unshare is unavailable")
    probe = subprocess.run(["unshare", "-cn", "--", "true"], capture_output=True, text=True)
    if probe.returncode:
        pytest.skip(f"cannot create a real user+network namespace: {probe.stderr.strip()}")
    monkeypatch.setenv("FARMER_SESSION_ID", "acceptance-afk-session")
    return launcher


def test_supervised_game_uses_loopback_only_namespace(supervised):
    (supervised.profile / "farmer.cfg").write_text('{"offline": false}')
    outer_netns = os.readlink("/proc/self/ns/net")
    supervised.run()
    record = supervised.record()
    assert record["netns"] != outer_netns
    assert record["interfaces"] == ["lo"]
    assert record["session_id"] == "acceptance-afk-session"
    assert os.readlink("/proc/self/ns/net") == outer_netns


def test_sandbox_launch_uses_separate_backup_directory(supervised, tmp_path, monkeypatch):
    backups = tmp_path / "sandbox backups"
    monkeypatch.setenv("FARMER_BACKUP_DIR", str(backups))

    supervised.run()

    snapshot, = backups.glob("[0-9]*")
    assert (snapshot / "profile.json").read_bytes() == PROFILE
    known_good = known_good_snapshot(backups)
    assert known_good is not None
    assert (known_good / "profile.json").read_bytes() == PROFILE
    assert not (supervised.data / "backups").exists()


@pytest.mark.parametrize("deny_actual_launch", [False, True])
def test_isolation_failure_is_fatal_before_game_exec(launcher, monkeypatch, tmp_path, deny_actual_launch):
    bin_dir = tmp_path / "unshare path"
    bin_dir.mkdir()
    if deny_actual_launch:
        # Fault injection at the OS seam: let the real unshare probe run but
        # reject the actual launch, which must not be mistaken for a game exit.
        real_unshare = shutil.which("unshare")
        if real_unshare is None:
            pytest.skip("util-linux unshare is unavailable")
        probe = subprocess.run([real_unshare, "-cn", "--", "true"], capture_output=True)
        if probe.returncode:
            pytest.skip(f"cannot create a real user+network namespace: {probe.stderr!r}")
        wrapper = bin_dir / "unshare"
        wrapper.write_text(
            f"#!{sys.executable}\nimport os, sys\n"
            f"args = sys.argv[1:] if sys.argv[-1] == 'true' else ['--reject-launch']\n"
            f"os.execv({real_unshare!r}, [{real_unshare!r}, *args])\n"
        )
        wrapper.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    else:
        monkeypatch.setenv("PATH", str(bin_dir))
    proc = launcher.run(78, "--session-id", "afk")
    assert "network isolation" in proc.stderr
    if deny_actual_launch:
        assert "reject-launch" in proc.stdout + proc.stderr
    assert not (launcher.profile / "fake-game.json").exists()


def test_read_only_profile_directory_is_unfixable_before_launch(launcher):
    launcher.profile.chmod(0o555)
    try:
        proc = launcher.run(78)
    finally:
        launcher.profile.chmod(0o755)
    assert "not writable" in proc.stderr
    assert not (launcher.profile / "fake-game.json").exists()


def test_nearly_full_profile_disk_is_unfixable_before_launch(launcher, monkeypatch):
    free = shutil.disk_usage(launcher.profile).free // (1024 * 1024)
    monkeypatch.setenv("FARMER_MIN_FREE_MB", str(free + 10))
    proc = launcher.run(78)
    assert "MiB free" in proc.stderr and f"below {free + 10} MiB" in proc.stderr
    assert not (launcher.profile / "fake-game.json").exists()


@pytest.mark.parametrize("cfg", ['{\"speed\": 10', "[]"])
def test_broken_farmer_config_is_unfixable_before_launch(launcher, cfg):
    (launcher.profile / "farmer.cfg").write_text(cfg)
    proc = launcher.run(78)
    assert "farmer.cfg is not a JSON object" in proc.stderr
    assert not (launcher.profile / "fake-game.json").exists()


def test_bad_preset_does_not_overwrite_config(launcher, tmp_path):
    preset = tmp_path / "invalid preset.json"
    preset.write_text("[]")
    assert "not a JSON object" in launcher.run(78, str(preset)).stderr
    assert (launcher.profile / "farmer.cfg").read_text() == "{}"
    assert not (launcher.profile / "fake-game.json").exists()


def test_display_override_runs_windowed_and_adjusts_config(launcher, monkeypatch):
    monkeypatch.setenv("FARMER_DISPLAY", "true")
    launcher.run()
    assert launcher.record()["args"] == []
    assert launcher.record()["config"] == {"display": True}


@pytest.mark.parametrize(("file", "contents", "detail"), [
    ("patches/patch_official.pck", b"official, next game version", "official patch changed"),
    ("patches/patch_official.pck", None, "official patch missing"),
    ("patches/patch_farmer.pck", b"stale", "installed farmer pack is stale"),
    ("patches/patch_farmer.pck", None, "farmer pack not installed"),
    ("patches/state.json", b'{"file":"patch_official.pck"}', "state.json does not mount"),
    ("patches/state.json", b"[]", "state.json is not a JSON object"),
    ("patches/state.json", None, "patches/state.json"),
    ("farmer.cfg", None, "no farmer.cfg"),
])
def test_profile_preflight_refuses_invalid_prerequisites(launcher, file, contents, detail):
    path = launcher.profile / file
    if contents is None:
        path.unlink()
    else:
        path.write_bytes(contents)
    assert detail in launcher.run(78).stderr
    assert not (launcher.profile / "fake-game.json").exists()


@pytest.mark.parametrize("file", ["patches/patch_official.pck", "patches/patch_farmer.pck",
                                 "patches/state.json", "farmer.cfg"])
def test_unreadable_preflight_input_is_unfixable(launcher, file):
    if os.geteuid() == 0:
        pytest.skip("root can read files with no read permissions")
    path = launcher.profile / file
    permissions = path.stat().st_mode
    path.chmod(0)
    try:
        result = launcher.run(78)
    finally:
        path.chmod(permissions)
    assert f"cannot read {path}" in result.stderr
    assert not (launcher.profile / "fake-game.json").exists()


@pytest.mark.parametrize("missing", ["game", "patch_info", "preset"])
def test_missing_launch_prerequisites_are_unfixable(launcher, missing, tmp_path):
    args = []
    if missing == "game":
        launcher.game.unlink()
        detail = "game not found"
    elif missing == "patch_info":
        patch_info.info_path(launcher.os_).unlink()
        detail = "no farmer patch info"
    else:
        args = [str(tmp_path / "missing preset")]
        detail = "preset not found"
    assert detail in launcher.run(78, *args).stderr
    assert not (launcher.profile / "fake-game.json").exists()


def test_unreadable_final_status_is_not_a_clean_finish(launcher):
    proc = launcher.run(1, mode="garbage")
    assert "did not finish cleanly" in proc.stderr


def test_stale_terminal_status_and_stop_request_do_not_survive_a_restart(supervised):
    status = supervised.profile / "farmer_status.json"
    stop = supervised.profile / "farmer_stop"
    previous_log = supervised.profile / "farmer.log"
    status.write_text('{"phase":"done","finish_reason":"max_runs"}')
    stop.touch()
    previous_log.write_text("previous attempt")

    supervised.run(1, mode="silent")

    assert not status.exists()
    assert not stop.exists()
    assert not previous_log.exists()
    assert (supervised.profile / "farmer.log.prev").read_text() == "previous attempt"
    assert known_good_snapshot(supervised.data / "backups") is None


def test_lock_file_left_by_a_dead_launcher_does_not_block(launcher):
    (launcher.profile / "farmer.run.lock").write_text("12345")
    launcher.run()
    assert (launcher.profile / "fake-game.json").exists()


@pytest.mark.parametrize(("lock_dir", "lock_name", "detail"), [
    ("profile", "farmer.run.lock", "another farmer launcher"),
    ("data", "service.lock", "already running"),
])
def test_second_launcher_is_transient_busy_without_touching_the_game(launcher, lock_dir, lock_name, detail):
    with launcher.os_.acquire_lock(getattr(launcher, lock_dir) / lock_name):
        proc = launcher.run(1)
    assert detail in proc.stderr
    assert not (launcher.profile / "fake-game.json").exists()


@pytest.mark.parametrize(("lock_dir", "lock_name"), [("profile", "farmer.run.lock"), ("data", "service.lock")])
def test_basic_preflight_failure_takes_precedence_over_busy_lock(launcher, lock_dir, lock_name):
    launcher.game.unlink()
    with launcher.os_.acquire_lock(getattr(launcher, lock_dir) / lock_name):
        assert "game not found" in launcher.run(78).stderr


def test_routine_backup_io_error_is_transient(launcher, tmp_path, monkeypatch):
    blocked = tmp_path / "not-a-directory"
    blocked.touch()
    monkeypatch.setenv("FARMER_BACKUP_DIR", str(blocked))
    assert str(blocked) in launcher.run(1).stderr
    assert not (launcher.profile / "fake-game.json").exists()


def test_broken_output_pipe_is_transient(launcher):
    with subprocess.Popen(launcher.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as service:
        service.stdout.close()
        assert service.wait(timeout=10) == 1
        assert b"Broken pipe" in service.stderr.read()


@pytest.mark.parametrize("same_worker", [True, False], ids=["same-worker", "other-worker"])
def test_only_a_game_with_the_workers_executable_name_blocks_launch(launcher, tmp_path, same_worker):
    name = launcher.game.name if same_worker else f"other-{launcher.game.name}"
    game_path = tmp_path / name
    game_path.symlink_to(os.path.realpath(sys.executable))
    command = [
        sys.executable, "-c",
        "import subprocess, sys\n"
        "with subprocess.Popen([sys.argv[1], '-c', 'import time; time.sleep(60)']) as game:\n"
        "    try:\n"
        "        code = subprocess.run([sys.executable, '-m', 'midgard_farm.service', 'launch']).returncode\n"
        "    finally:\n"
        "        game.kill()\n"
        "raise SystemExit(code)\n",
        str(game_path),
    ]
    proc = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=10)
    assert proc.returncode == int(same_worker), proc.stdout + proc.stderr
    if same_worker:
        assert "game is already running" in proc.stderr
        assert not (launcher.profile / "fake-game.json").exists()
        assert not (launcher.data / "backups").exists()
    else:
        assert launcher.record()["cwd"] == str(launcher.game.parent)


@pytest.mark.parametrize(("mode", "code"), [("fail", 1), ("done-9", 9), ("kill", 137), ("done-137", 0)])
def test_isolated_exit_status_and_tee(supervised, mode, code):
    proc = supervised.run(code, mode=mode)
    log, = (supervised.data / "logs").glob("run-*.log")
    for message in ("fake game stdout", "fake game stderr"):
        assert message in proc.stdout
        assert message in log.read_text()


def send_signal_during_game(launcher, signum, mode, code, *, grace=None):
    command = launcher.command
    if grace is not None:
        command = [
            sys.executable, "-c",
            "from midgard_farm.core import launch\n"
            f"launch.SHUTDOWN_GRACE_SECONDS = {grace}\n"
            "from midgard_farm.service import main\n"
            "raise SystemExit(main())\n",
            "launch",
        ]
    proc = subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, env={**os.environ, "FAKE_GAME_MODE": mode},
    )
    game_fd = None
    try:
        deadline = time.monotonic() + 5
        while not (launcher.profile / "fake-game.json").exists():
            assert proc.poll() is None and time.monotonic() < deadline, "fake game did not start"
            time.sleep(0.01)

        def child_pid(pid):
            child, = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
            return int(child)

        service_pid = proc.pid
        game_pid = child_pid(service_pid)
        game_fd = os.pidfd_open(game_pid)
        started = time.monotonic()
        os.kill(service_pid, signum)
        assert proc.wait(timeout=5) == code
        elapsed = time.monotonic() - started
        with pytest.raises(ProcessLookupError):
            os.kill(game_pid, 0)
        return elapsed
    finally:
        if game_fd is not None:
            try:
                signal.pidfd_send_signal(game_fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
            finally:
                os.close(game_fd)
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_supervisor_signal_requests_clean_finish_and_publishes_known_good(supervised, signum):
    send_signal_during_game(supervised, signum, "finish-on-stop", 0)
    status = json.loads((supervised.profile / "farmer_status.json").read_text())
    assert status["phase"] == "done" and not status["failed"]
    snapshot = known_good_snapshot(supervised.data / "backups")
    assert snapshot is not None
    assert (snapshot / "profile.json").read_bytes() == b"settled after shutdown request"


@pytest.mark.parametrize("signum", [getattr(signal, "SIGHUP", None), getattr(signal, "SIGQUIT", None)])
def test_manual_launch_reaps_game_that_ignores_shutdown_after_grace(launcher, signum):
    grace = 0.3
    elapsed = send_signal_during_game(launcher, signum, "ignore-stop", 137, grace=grace)
    assert elapsed >= grace
    assert (launcher.profile / "farmer_stop").is_file()
    assert not (launcher.profile / "farmer_status.json").exists()


def manifest_digest(name, contents):
    return f"{hashlib.sha256(contents).hexdigest()}  {name}\n"


def test_failed_restarts_rotate_routine_snapshots_not_known_good(supervised):
    backups = supervised.data / "backups"
    backups.mkdir()
    (backups / "official-state.json").write_text("official state")
    supervised.run(137, mode="kill")
    assert known_good_snapshot(backups) is None
    supervised.run()
    known_good = known_good_snapshot(backups)
    assert known_good is not None
    assert (known_good / "profile.json").read_bytes() == PROFILE
    assert (known_good / "profile.bak.json").read_bytes() == COMPANION
    manifest = manifest_digest("profile.json", PROFILE) + manifest_digest("profile.bak.json", COMPANION)
    assert (known_good / "SHA256SUMS").read_text() == manifest
    for i in range(12):
        (supervised.profile / "profile.json").write_bytes(f"damaged {i}".encode())
        supervised.run(1, mode="fail")
    assert known_good_snapshot(backups) == known_good
    assert (known_good / "profile.json").read_bytes() == PROFILE
    assert (known_good / "SHA256SUMS").read_text() == manifest
    assert (backups / "official-state.json").read_text() == "official state"
    assert sorted(path.read_bytes() for path in backups.glob("[0-9]*/profile.json")) == sorted(
        f"damaged {i}".encode() for i in range(2, 12)
    )


@pytest.mark.parametrize("reason", ["abort", "lost_world", "unknown"])
def test_unsettled_terminal_outcome_does_not_replace_known_good(supervised, monkeypatch, reason):
    supervised.run()
    backups = supervised.data / "backups"
    known_good = known_good_snapshot(backups)
    assert known_good is not None
    manifest = (known_good / "SHA256SUMS").read_bytes()
    (supervised.profile / "profile.json").write_bytes(b"new bytes from an unsettled run")
    monkeypatch.setenv("FAKE_GAME_FINISH_REASON", reason)

    supervised.run(mode="done-137")

    assert json.loads((supervised.profile / "farmer_status.json").read_text())["finish_reason"] == reason
    assert known_good_snapshot(backups) == known_good
    assert (known_good / "profile.json").read_bytes() == PROFILE
    assert (known_good / "SHA256SUMS").read_bytes() == manifest


def test_copy_verification_keeps_previous_known_good_on_bad_copy_or_empty_profile(supervised, tmp_path, monkeypatch):
    import resource

    backups = tmp_path / "sandbox backups"
    monkeypatch.setenv("FARMER_BACKUP_DIR", str(backups))
    supervised.run()
    known_good = known_good_snapshot(backups)
    assert known_good is not None
    assert not (supervised.data / "backups").exists()
    manifest = (known_good / "SHA256SUMS").read_bytes()

    (supervised.profile / "profile.json").write_bytes(b"")
    assert "copy verification failed" in supervised.run().stderr
    assert (known_good / "profile.json").read_bytes() == PROFILE

    # Make a real OS copy fail after the game saves a larger profile without
    # substituting the service's copy or hash implementation.
    def limit_copy_size():
        _, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024, hard))

    proc = supervised.run(mode="large-profile", preexec_fn=limit_copy_size)
    assert "copy verification failed" in proc.stderr
    assert (supervised.profile / "profile.json").stat().st_size == 4096
    assert known_good_snapshot(backups) == known_good
    assert (known_good / "SHA256SUMS").read_bytes() == manifest
    assert (known_good / "profile.json").read_bytes() == PROFILE

    updated = b"\xffnew binary profile\x00"
    (supervised.profile / "profile.json").write_bytes(updated)
    supervised.run(mode="done-137")
    previous = known_good
    known_good = known_good_snapshot(backups)
    assert known_good is not None and known_good != previous
    assert not previous.exists()
    assert (known_good / "profile.json").read_bytes() == updated
    assert (known_good / "SHA256SUMS").read_text() == (
        manifest_digest("profile.json", updated) + manifest_digest("profile.bak.json", COMPANION)
    )


def test_known_good_publication_creates_backup_directory_and_preserves_pointer_on_write_failure(
    launcher, tmp_path, monkeypatch,
):
    backups = tmp_path / "new backup root" / "backups"
    publish_known_good(launcher.os_, launcher.profile, backups)
    pointer = backups / "known-good/current"
    published = pointer.read_bytes()
    generation = pointer.parent / published.decode("ascii")
    assert (generation / "profile.json").read_bytes() == PROFILE
    (launcher.profile / "profile.json").write_bytes(b"new save")

    replace = launcher.os_.replace_atomic

    def fail_pointer_replace(src, dst):
        if dst == pointer:
            raise OSError("simulated pointer write failure")
        replace(src, dst)

    monkeypatch.setattr(launcher.os_, "replace_atomic", fail_pointer_replace)
    with pytest.raises(OSError, match="simulated pointer write failure"):
        publish_known_good(launcher.os_, launcher.profile, backups)
    assert pointer.read_bytes() == published
    assert (generation / "profile.json").read_bytes() == PROFILE
