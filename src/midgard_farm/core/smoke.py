"""Prove the built farmer patch without mounting it in the real profile."""

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..platform import Platform
from . import farmer_patch
from .patch_info import INSTALLED_PACK

_TIMEOUT_SECONDS = 300
_BUSY_REASON = "the game is running; close it first"
_STOP_REASON = "service stopped during smoke"
_SCRIPT_ERROR = re.compile(rb"SCRIPT ERROR|Parse Error|Invalid call|Cannot call method")
_FINISH = re.compile(rb"^(?:FARMER \S+ )?FINISH\b")

# The built-in verify.sh --one-run preset; independent of the operator's preset.
_ONE_RUN = {
    "objective": "balanced", "class": "swordsman", "stage": "prontera", "danger": 1,
    "speed": 10.0, "game_speed": 3, "max_runs": 1, "run_minutes": 12, "restart_seconds": 1,
    "auto_keep": False, "auto_stats": True, "auto_achievements": True, "auto_fuse": False,
    "auto_cards": False, "auto_upgrades": False, "auto_sage": False, "auto_loadout": False,
    "auto_pet": False, "auto_rebirth": False, "auto_rebirth_lv": False, "endless": False,
    "display": False, "offline": True, "hard_exit": True,
}
_STALE = {
    "farmer.cfg", "farmer_command", "farmer_command.claimed", "farmer_stop", "farmer_status.json",
    "farmer.log", "farmer.log.prev", "farmer.run.lock", "farmer_runs.jsonl", "farmer_session.json",
    "farmer_supervisor.lock", "farmer_supervisor_session", "farmer_test_crashed",
}


def one_run_config() -> dict[str, object]:
    return _ONE_RUN.copy()


class SmokeOutcome(Enum):
    PASSED = "passed"
    FAILED = "failed"
    BUSY = "busy"
    STOPPED = "stopped"


@dataclass(frozen=True)
class SmokeVerdict:
    outcome: SmokeOutcome
    reason: str
    attempts: int
    log_path: Path | None

    @property
    def passed(self) -> bool:
        return self.outcome is SmokeOutcome.PASSED


def _copy_profile(os_: Platform, profile: Path, sandbox: Path) -> None:
    patches = profile / "patches"

    def ignore(directory: str, names: list[str]) -> set[str]:
        if Path(directory) == profile:
            return _STALE.intersection(names)
        if Path(directory) == patches and INSTALLED_PACK in names:
            # The public install will stage a new candidate; there's no old sandbox pack to back up.
            return {INSTALLED_PACK}
        return set()

    def transfer(src: str, dst: str) -> None:
        source = Path(src)
        if source.parent == patches and source.suffix.lower() == ".pck":
            os_.link_sandbox_pack(source, Path(dst))
        else:
            # Mutable files, including any symlink targets, must have their own inode.
            shutil.copyfile(src, dst)

    shutil.copytree(profile, sandbox, ignore=ignore, copy_function=transfer)


def _number(value: object) -> int | float:
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        return value
    return 0


def _has_marker(path: Path, marker: re.Pattern[bytes]) -> bool:
    try:
        with path.open("rb") as lines:
            return any(marker.search(line) for line in lines)
    except FileNotFoundError:
        return False


def has_script_error(log_path: Path) -> bool:
    return _has_marker(log_path, _SCRIPT_ERROR)


def judge_one_run(os_: Platform, profile: Path, log_path: Path) -> str:
    if has_script_error(log_path):
        return "script error in game output"
    try:
        status = json.loads(os_.read_shared(profile / "farmer_status.json", retry_missing=True))
    except FileNotFoundError:
        return "no farmer_status.json"
    except ValueError:
        return "invalid farmer_status.json"
    if not isinstance(status, dict):
        return "invalid farmer_status.json"
    if status.get("phase") != "done":
        return "farmer status is not done"
    if status.get("failed"):
        return "farmer status is failed"
    totals = status.get("totals")
    if not isinstance(totals, dict) or _number(totals.get("wins")) < 1:
        return "no wins recorded"
    last = status.get("last")
    if not isinstance(last, dict) or last.get("victory") is not True:
        return "last run was not a victory"
    if _number(last.get("kills")) <= 0:
        return "no kills in the last run"
    if _number(last.get("zeny_gain")) <= 0:
        return "no zeny gained in the last run"
    if not _has_marker(profile / "farmer.log", _FINISH):
        return "missing FINISH marker"
    return ""


class _SmokeStopped(Exception):
    pass


def prepare_sandbox(
    os_: Platform, profile: Path, data_home: Path, *, stop_requested: Callable[[], bool] = lambda: False,
) -> tuple[Path, dict[str, str]]:
    """Copy the profile and mount the built farmer patch only in the redirected user data."""
    godot_root, env = os_.godot_sandbox(data_home)
    sandbox = godot_root / profile.name
    if stop_requested():
        raise _SmokeStopped
    _copy_profile(os_, profile, sandbox)
    if stop_requested():
        raise _SmokeStopped
    farmer_patch.install(os_, sandbox, backup_dir=data_home / "install-backups")
    return sandbox, env


def _attempt(
    os_: Platform, profile: Path, app_dir: Path, game: Path, log_path: Path, stop_requested: Callable[[], bool],
) -> str:
    data_home = Path(tempfile.mkdtemp(dir=app_dir, prefix="smoke-"))
    try:
        sandbox, env = prepare_sandbox(os_, profile, data_home, stop_requested=stop_requested)
        os_.write_atomic(sandbox / "farmer.cfg", json.dumps(_ONE_RUN).encode())
        env["FARMER_SESSION"] = "1"
        env.pop("FARMER_SESSION_ID", None)
        if os_.game_running():
            raise farmer_patch.GameRunning(_BUSY_REASON)
        if stop_requested():
            raise _SmokeStopped
        with log_path.open("wb") as output:
            try:
                with os_.spawn_tree(
                    [str(game), "--headless"], cwd=game.parent, env=env, stdout=output,
                    stderr=subprocess.STDOUT, isolate_network=True,
                ) as tree:
                    deadline = time.monotonic() + _TIMEOUT_SECONDS
                    while not stop_requested():
                        seconds_left = deadline - time.monotonic()
                        if seconds_left <= 0:
                            raise subprocess.TimeoutExpired([str(game), "--headless"], _TIMEOUT_SECONDS)
                        try:
                            code = tree.wait(timeout=min(seconds_left, 0.2))
                            break
                        except subprocess.TimeoutExpired:
                            continue
                    else:
                        raise _SmokeStopped
            except subprocess.TimeoutExpired:
                # Leaving the tree context kills it and reaps the game before a retry.
                return f"game timed out after {_TIMEOUT_SECONDS:g} s"
        # A verified headless finish can SIGKILL itself; on Windows the exit code is not meaningful.
        if os_.game_exit_status_reliable and code not in (0, -9):
            return f"game exited with code {code}"
        return judge_one_run(os_, sandbox, log_path)
    finally:
        # TemporaryDirectory can chmod files on cleanup; a linked pack must never be chmodded.
        shutil.rmtree(data_home)


def run_smoke(
    os_: Platform, profile: Path, *, stop_requested: Callable[[], bool] = lambda: False,
) -> SmokeVerdict:
    """Play at most two fresh sandbox attempts; stop promptly if requested."""
    if stop_requested():
        return SmokeVerdict(SmokeOutcome.STOPPED, _STOP_REASON, 0, None)
    try:
        if os_.game_running():
            return SmokeVerdict(SmokeOutcome.BUSY, _BUSY_REASON, 0, None)
        game = os_.game_executable().absolute()
        if not game.is_file() or not os.access(game, os.X_OK):
            return SmokeVerdict(SmokeOutcome.FAILED, f"game not found or not executable at {game}", 0, None)
        app_dir = os_.app_data_dir().resolve()
        logs = (app_dir / "logs").resolve()
        profile = profile.absolute()
        real = profile.resolve(strict=True)
        if app_dir.is_relative_to(real) or logs.is_relative_to(real):
            return SmokeVerdict(SmokeOutcome.FAILED, "smoke data directory overlaps the real profile", 0, None)
        logs.mkdir(parents=True, exist_ok=True)
        log_dir = Path(tempfile.mkdtemp(dir=logs, prefix="smoke-"))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return SmokeVerdict(SmokeOutcome.FAILED, " ".join(str(exc).splitlines()), 0, None)

    last_log = None
    for attempt in (1, 2):
        log_path = log_dir / f"attempt-{attempt}.log"
        try:
            if stop_requested():
                return SmokeVerdict(SmokeOutcome.STOPPED, _STOP_REASON, attempt - 1, last_log)
            if os_.game_running():
                return SmokeVerdict(SmokeOutcome.BUSY, _BUSY_REASON, attempt - 1, last_log)
            reason = _attempt(os_, profile, app_dir, game, log_path, stop_requested)
        except _SmokeStopped:
            if log_path.exists():
                return SmokeVerdict(SmokeOutcome.STOPPED, _STOP_REASON, attempt, log_path)
            return SmokeVerdict(SmokeOutcome.STOPPED, _STOP_REASON, attempt - 1, last_log)
        except farmer_patch.GameRunning as exc:
            return SmokeVerdict(SmokeOutcome.BUSY, str(exc), attempt - 1, last_log)
        except (OSError, farmer_patch.InstallFailed, subprocess.SubprocessError) as exc:
            reason = " ".join(str(exc).splitlines()) or type(exc).__name__
        last_log = log_path if log_path.is_file() else None
        if stop_requested():
            return SmokeVerdict(SmokeOutcome.STOPPED, _STOP_REASON, attempt, last_log)
        if not reason:
            return SmokeVerdict(SmokeOutcome.PASSED, "smoke passed", attempt, last_log)
    return SmokeVerdict(SmokeOutcome.FAILED, reason, attempt, last_log)
