"""The service entry point, run as a process against a temporary user dir."""

import os
import subprocess
import sys

from midgard_farm import platform

from test_profile import godot_root, make_profile


def run_service(home):
    env = dict(os.environ, XDG_DATA_HOME=str(home), APPDATA=str(home), LOCALAPPDATA=str(home))
    return subprocess.run(
        [sys.executable, "-m", "midgard_farm.service"],
        env=env, capture_output=True, encoding="utf-8", timeout=30,
    )


def test_service_reports_the_profile_it_found(tmp_path):
    profile = make_profile(godot_root(tmp_path), "Мидгард Survivors")

    result = run_service(tmp_path)

    assert result.returncode == 0, result.stderr
    assert str(profile) in result.stdout


def test_service_without_profile_exits_unfixable(tmp_path):
    result = run_service(tmp_path)

    assert result.returncode == 78
    assert "launch the game once" in result.stderr


def test_second_service_instance_is_refused(tmp_path, monkeypatch):
    make_profile(godot_root(tmp_path), "Midgard Survivors")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    os_.app_data_dir().mkdir(parents=True)

    with os_.acquire_lock(os_.app_data_dir() / "service.lock"):
        result = run_service(tmp_path)

    assert result.returncode == 75
    assert "already running" in result.stderr
