"""Exercise run.sh with a fake game, an isolated XDG home, and real Linux netns."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time

import pytest


HERE = Path(__file__).resolve().parent
PROFILE = b"\x00\xffopaque Godot profile\x80"
COMPANION = b"\x00\x81previous profile"


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    farmer = tmp_path / "fake farmer"
    farmer.mkdir()
    run = farmer / "run.sh"
    shutil.copy2(HERE.parent / "run.sh", run)
    xdg = tmp_path / "xdg"
    data = xdg / "godot/app_userdata/Midgard Survivors"
    patches = data / "patches"
    patches.mkdir(parents=True)
    official = patches / "patch_official.pck"
    built = patches / "patch_farmer.pck"
    official.write_bytes(b"official")
    built.write_bytes(b"farmer")
    (patches / "state.json").write_text('{"file":"patch_farmer.pck"}')
    (farmer / "patch_farmer.info").write_text(
        f"PATCH_FILE={official.name}\n"
        f"PATCH_SHA256={hashlib.sha256(official.read_bytes()).hexdigest()}\n"
        f"PATCH_FARMER_SHA256={hashlib.sha256(built.read_bytes()).hexdigest()}\n"
    )
    (data / "farmer.cfg").write_text("{}")
    (data / "profile.json").write_bytes(PROFILE)
    (data / "profile.bak.json").write_bytes(COMPANION)
    game_dir = tmp_path / "fake-install"
    game_dir.mkdir()
    executable = shutil.copyfile(HERE / "runsh_fake_game.py", game_dir / "MidgardSurvivors.x86_64")
    Path(executable).chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # The process scan is global; an external real-game smoke must not block this fixture.
    shim(bin_dir, "pgrep", "exit 1")
    for name in ("FARMER_SESSION_ID", "FARMER_BACKUP_DIR", "FARMER_DISPLAY", "RUNSH_FAKE_MODE",
                 "RUNSH_FAKE_FINISH_REASON"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.setenv("GAME_DIR", str(game_dir))
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return run, data, bin_dir


def shim(bin_dir, name, body):
    script = bin_dir / name
    script.write_text(f"#!/usr/bin/env bash\n{body}\n")
    script.chmod(0o755)


@pytest.fixture
def supervised(launcher, monkeypatch):
    if not shutil.which("unshare"):
        pytest.skip("util-linux unshare is unavailable")
    probe = subprocess.run(["unshare", "-cn", "--", "true"], capture_output=True, text=True)
    if probe.returncode:
        pytest.skip(f"cannot create a real user+network namespace: {probe.stderr.strip()}")
    monkeypatch.setenv("FARMER_SESSION_ID", "acceptance-afk-session")
    return launcher


def launch(run, code=0, *, mode="done"):
    proc = subprocess.run(
        [run], capture_output=True, text=True, timeout=10,
        env={**os.environ, "RUNSH_FAKE_MODE": mode},
    )
    assert proc.returncode == code, proc.stdout + proc.stderr
    return proc


def game_record(data):
    return json.loads((data / "fake-game.json").read_text())


def test_supervised_game_uses_loopback_only_namespace(supervised):
    run, data, _ = supervised
    (data / "farmer.cfg").write_text('{"offline": false}')
    outer_netns = os.readlink("/proc/self/ns/net")
    launch(run)
    record = game_record(data)
    assert record["netns"] != outer_netns
    assert record["interfaces"] == ["lo"]
    assert os.readlink("/proc/self/ns/net") == outer_netns


def test_manual_launch_keeps_network_and_needs_no_unshare(launcher):
    run, data, bin_dir = launcher
    shim(bin_dir, "unshare", "exit 99")
    launch(run)
    record = game_record(data)
    assert record["netns"] == os.readlink("/proc/self/ns/net")
    assert record["interfaces"] == sorted(name for _, name in socket.if_nameindex())
    assert not (run.parent / "backups/known-good").exists()


def test_sandbox_install_uses_separate_backup_directory(launcher, monkeypatch):
    run, data, _ = launcher
    farm = run.parent
    install = farm / "install.sh"
    shutil.copy2(HERE.parent / "install.sh", install)
    patches = data / "patches"
    (patches / "state.json").write_text('{"file":"patch_official.pck"}')
    shutil.copyfile(patches / "patch_farmer.pck", farm / "patch_farmer.pck")
    (farm / "farmer_build.json").write_text("{}")
    backups = farm / "sandbox backups"
    monkeypatch.setenv("FARMER_BACKUP_DIR", str(backups))

    launch(install)

    snapshot, = (path for path in backups.iterdir() if path.is_dir())
    assert (snapshot / "profile.json").read_bytes() == PROFILE
    assert (backups / "official-state.json").read_bytes() == (snapshot / "state.json").read_bytes()
    assert not (farm / "backups").exists()


@pytest.mark.parametrize("deny_actual_launch", [False, True])
def test_isolation_failure_is_fatal_before_game_exec(launcher, monkeypatch, deny_actual_launch):
    run, data, bin_dir = launcher
    monkeypatch.setenv("FARMER_SESSION_ID", "acceptance-afk-session")
    let_probe_pass = '[[ "${*: -1}" == "true" ]] && exit 0\n' if deny_actual_launch else ""
    shim(bin_dir, "unshare", let_probe_pass + 'echo "namespace permission denied" >&2\nexit 1')
    proc = launch(run, 78)
    assert "network isolation" in proc.stderr
    assert "namespace permission denied" in proc.stdout + proc.stderr
    assert not (data / "fake-game.json").exists()


def test_read_only_profile_directory_is_unfixable_before_launch(launcher):
    run, data, _ = launcher
    data.chmod(0o555)
    try:
        proc = launch(run, 78)
    finally:
        data.chmod(0o755)
    assert "not writable" in proc.stderr
    assert not (data / "fake-game.json").exists()


def test_nearly_full_profile_disk_is_unfixable_before_launch(launcher):
    run, data, bin_dir = launcher
    shim(bin_dir, "df", 'echo "Filesystem 1024-blocks Used Available Capacity Mounted on"\n'
                        'echo "/dev/fake 1000000 900000 102400 90% /"')  # 100 MiB free
    proc = launch(run, 78)
    assert "100 MiB free" in proc.stderr
    assert not (data / "fake-game.json").exists()


@pytest.mark.parametrize("cfg", ['{"speed": 10', "[]"])
def test_broken_farmer_config_is_unfixable_before_launch(launcher, cfg):
    run, data, _ = launcher
    (data / "farmer.cfg").write_text(cfg)
    proc = launch(run, 78)
    assert "farmer.cfg is not a JSON object" in proc.stderr
    assert not (data / "fake-game.json").exists()


def test_official_patch_update_is_unfixable_before_launch(launcher):
    run, data, _ = launcher
    (data / "patches/patch_official.pck").write_bytes(b"official, next game version")
    proc = launch(run, 78)
    assert "official patch changed" in proc.stderr
    assert not (data / "fake-game.json").exists()


def test_unreadable_final_status_is_not_a_clean_finish(launcher):
    run, _, _ = launcher
    proc = launch(run, 1, mode="garbage")
    assert "did not finish cleanly" in proc.stderr


def test_lock_file_left_by_a_dead_launcher_does_not_block(launcher):
    run, data, _ = launcher
    (data / "farmer.run.lock").write_text("12345")  # its flock died with the launcher
    launch(run)
    assert (data / "fake-game.json").exists()


def test_second_launcher_is_transient_busy_without_touching_the_game(launcher):
    run, data, _ = launcher
    with open(data / "farmer.run.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the first launcher
        proc = launch(run, 1)
    assert "another farmer launcher" in proc.stderr
    assert not (data / "fake-game.json").exists()


@pytest.mark.parametrize(("mode", "code"), [("fail", 1), ("done-9", 9), ("kill", 137), ("done-137", 0)])
def test_isolated_exit_status_and_tee(supervised, mode, code):
    run, _, _ = supervised
    proc = launch(run, code, mode=mode)
    log, = (run.parent / "logs").glob("run-*.log")
    for message in ("fake game stdout", "fake game stderr"):
        assert message in proc.stdout
        assert message in log.read_text()


def test_supervisor_group_signal_reaches_isolated_game(supervised):
    run, data, _ = supervised
    with subprocess.Popen(
        [run], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        env={**os.environ, "RUNSH_FAKE_MODE": "wait"},
    ) as proc:
        try:
            deadline = time.monotonic() + 5
            while not (data / "fake-game.json").exists() and proc.poll() is None:
                if time.monotonic() >= deadline:
                    pytest.fail("fake game did not start")
                time.sleep(0.01)
            assert game_record(data)["pgrp"] == proc.pid
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)
            assert (data / "fake-game.term").exists()
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)


def manifest_digest(name, contents):
    return f"{hashlib.sha256(contents).hexdigest()}  {name}\n"


def test_failed_restarts_rotate_routine_snapshots_not_known_good(supervised):
    run, data, _ = supervised
    backups = run.parent / "backups"
    backups.mkdir()
    (backups / "official-state.json").write_text("official state")
    known_good = backups / "known-good"
    launch(run, 137, mode="kill")
    assert not known_good.exists()
    launch(run)
    assert (known_good / "profile.json").read_bytes() == PROFILE
    assert (known_good / "profile.bak.json").read_bytes() == COMPANION
    manifest = manifest_digest("profile.json", PROFILE) + manifest_digest("profile.bak.json", COMPANION)
    assert (known_good / "SHA256SUMS").read_text() == manifest
    for i in range(12):
        (data / "profile.json").write_bytes(f"damaged {i}".encode())
        launch(run, 1, mode="fail")
    assert (known_good / "profile.json").read_bytes() == PROFILE
    assert (known_good / "SHA256SUMS").read_text() == manifest
    assert (backups / "official-state.json").read_text() == "official state"
    snapshots = [path / "profile.json" for path in backups.glob("[0-9]*")]
    assert sorted(path.read_bytes() for path in snapshots) == sorted(
        f"damaged {i}".encode() for i in range(2, 12)
    )


@pytest.mark.parametrize("reason", ["abort", "lost_world", "unknown"])
def test_unsettled_terminal_outcome_does_not_replace_known_good(supervised, monkeypatch, reason):
    run, data, _ = supervised
    launch(run)
    known_good = run.parent / "backups/known-good"
    manifest = (known_good / "SHA256SUMS").read_bytes()
    (data / "profile.json").write_bytes(b"new bytes from an unsettled run")
    monkeypatch.setenv("RUNSH_FAKE_FINISH_REASON", reason)

    launch(run, mode="done-137")

    assert json.loads((data / "farmer_status.json").read_text())["finish_reason"] == reason
    assert (known_good / "profile.json").read_bytes() == PROFILE
    assert (known_good / "SHA256SUMS").read_bytes() == manifest


def test_copy_verification_keeps_previous_known_good_on_bad_copy_or_empty_profile(supervised, monkeypatch):
    run, data, bin_dir = supervised
    backups = run.parent / "sandbox backups"
    monkeypatch.setenv("FARMER_BACKUP_DIR", str(backups))
    launch(run)
    known_good = backups / "known-good"
    assert not (run.parent / "backups").exists()
    manifest = (known_good / "SHA256SUMS").read_bytes()
    (data / "profile.json").write_bytes(b"")
    assert "copy verification failed" in launch(run).stderr
    assert (known_good / "profile.json").read_bytes() == PROFILE

    updated = b"\xffnew binary profile\x00"
    (data / "profile.json").write_bytes(updated)
    real_cp = shutil.which("cp")
    shim(bin_dir, "cp", f'''"{real_cp}" "$@" || exit $?
source="${{@: -2:1}}"
if [[ "$source" == */profile.json && "$source" != "$XDG_DATA_HOME/godot/app_userdata/Midgard Survivors/profile.json" ]]; then
    printf "corrupt copy" > "${{@: -1}}"
fi''')
    assert "copy verification failed" in launch(run).stderr
    assert (known_good / "SHA256SUMS").read_bytes() == manifest
    assert (known_good / "profile.json").read_bytes() == PROFILE

    (bin_dir / "cp").unlink()
    launch(run, mode="done-137")
    assert (known_good / "profile.json").read_bytes() == updated
    assert (known_good / "SHA256SUMS").read_text() == (
        manifest_digest("profile.json", updated) + manifest_digest("profile.bak.json", COMPANION)
    )
