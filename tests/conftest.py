"""Keep fake games that use the real process scanner private to each worker."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from midgard_farm import platform


@pytest.fixture(autouse=True)
def no_real_user_services(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests off the operator's real systemd user manager.

    2026-11-20: a test registered and enabled ~/.config/systemd/user/midgard-farm.service
    pointing into a pytest temp dir. Unit files go to a temp XDG_CONFIG_HOME, and any
    unfaked `systemctl`/`systemd-run` call fails the test. Tests that fake subprocess.run
    themselves replace this guard.
    """
    if sys.platform == "win32":
        return  # CI exercises the real Task Scheduler with unique task names.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg-config")))
    real_run = subprocess.run

    def guarded_run(args, *rest, **kwargs):
        argv = [args] if isinstance(args, (str, os.PathLike)) else list(args)
        if argv and os.path.basename(os.fspath(argv[0])) in {"systemctl", "systemd-run"}:
            raise AssertionError(f"test called the real user service manager: {argv}")
        return real_run(args, *rest, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)


@pytest.fixture(scope="session")
def fake_game_name() -> str:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "serial")
    # Worker names repeat across independent pytest invocations.
    return f"midgard-test-{worker}-{os.getpid()}{platform.current().executable_suffix}"


@pytest.fixture
def game_platform(monkeypatch: pytest.MonkeyPatch, fake_game_name: str) -> platform.Platform:
    os_ = platform.current()
    monkeypatch.setattr(type(os_), "game_exe_name", fake_game_name)
    return os_


@pytest.fixture
def service_game_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, game_platform: platform.Platform,
) -> tuple[platform.Platform, Path]:
    # Apply the same name in fresh interpreters, including `python -m midgard_farm.service`.
    startup = tmp_path / "sitecustomize.py"
    startup.write_text(
        "from midgard_farm import platform\n"
        f"type(platform.current()).game_exe_name = {game_platform.game_exe_name!r}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path), prepend=os.pathsep)
    return game_platform, startup
