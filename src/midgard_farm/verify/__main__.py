"""Run real-game verification on throwaway profile copies; never run it in CI."""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .. import platform
from ..core import farmer_patch, patch_info
from ..core.launch import shutdown_request
from ..core.profile import ProfileNotFound, find_profile
from .scenarios import BOUNDED_SCENARIOS, check_supported, run_scenario


def wait_for_lock(os_: platform.Platform, path: Path, deadline: float,
                  stop: Callable[[], float | None]) -> platform.InstanceLock:
    reported = False
    while stop() is None:
        try:
            return os_.acquire_lock(path)
        except platform.LockHeld:
            if not reported:
                print(f"verify: another verification holds {path}; waiting", flush=True)
                reported = True
            if (left := deadline - time.monotonic()) <= 0:
                raise TimeoutError(f"timed out waiting for {path}") from None
            time.sleep(min(left, 0.2))
    raise InterruptedError("interrupted waiting for verification lock")


def _hours(value: str) -> float:
    try:
        hours = float(value)
    except ValueError:
        hours = 0
    if hours <= 0 or not math.isfinite(hours * 3600):
        raise argparse.ArgumentTypeError("expected a positive, finite number of hours")
    return hours


def _worker(argv: list[str]) -> int:
    source, candidate, work, name, hours, preset = argv
    work_path = Path(work)
    out = work_path.parents[1]
    interrupted_at = None
    with shutdown_request() as signal_at:
        def requested() -> float | None:
            nonlocal interrupted_at
            if interrupted_at is None:
                interrupted_at = signal_at()
                if interrupted_at is None and (out / ".stop").exists():
                    interrupted_at = time.monotonic()
            return interrupted_at

        try:
            result = run_scenario(platform.current(), Path(source), Path(candidate), work_path, out, name,
                                  hours=float(hours), soak_preset=Path(preset) if preset else None,
                                  stop_requested_at=requested)
        except InterruptedError as exc:
            print(f"verify: {exc}", file=sys.stderr)
            return 130
        except (ValueError, OSError, RuntimeError, platform.LockHeld, patch_info.PatchInfoError,
                farmer_patch.GameRunning, farmer_patch.InstallFailed) as exc:
            print(f"verify: {exc}", file=sys.stderr)
            return 2
    return 130 if result["exit"] == 130 else int(result["verdict"] != "PASS")


def _launch_worker(os_: platform.Platform, out: Path, source: Path, candidate: Path, game: Path,
                   name: str, hours: float, preset: Path | None, stop: Callable[[], float | None]) -> int:
    work = out / "sandbox" / name
    work.mkdir(parents=True)
    env = os_.app_sandbox_environment(work)
    env["GAME_DIR"] = str(game.parent)
    argv = [sys.executable, "-B", "-m", "midgard_farm.verify", "_worker", str(source), str(candidate), str(work),
            name, str(hours), str(preset) if preset else ""]
    with (out / f"{name}.worker.log").open("wb") as log, subprocess.Popen(
            argv, env=env, stdout=log, stderr=subprocess.STDOUT) as worker:
        while True:
            try:
                return worker.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                if stop() is not None:
                    # Polled by the child, which owns the game tree and reaps it.
                    (out / ".stop").touch()


def _print_summary(rows: list[dict]) -> None:
    print("\n| scenario | result | exit | phase | runs/wins | kills | zeny |")
    print("|---|---|---|---|---|---|---|")
    for row in rows:
        kills = (row.get("last") or {}).get("kills")
        print(f"| {row['scenario']} | {row['verdict']} | {row['exit']} | {row.get('phase') or '-'} | "
              f"{row.get('runs')}/{row.get('wins')} | {kills} | {row.get('zeny')} |")


def _suite(os_: platform.Platform, out: Path, source: Path, candidate: Path, game: Path, names: tuple[str, ...], *,
           hours: float, preset: Path | None, keep: bool, stop: Callable[[], float | None]) -> int:
    # Pin one build for the suite, even if the app publishes another candidate meanwhile.
    staged = out / "sandbox" / "candidate"
    staged.mkdir(parents=True)
    metadata = patch_info.info_path(os_).name
    shutil.copyfile(candidate / metadata, staged / metadata)
    info = patch_info.load(staged / metadata)
    os_.link_sandbox_pack(candidate / patch_info.INSTALLED_PACK, staged / patch_info.INSTALLED_PACK)
    print(f"verify: artifacts {out}\nverify: build {info.result_sha256}", flush=True)
    rows: list[dict] = []
    exit_code = 0
    for name in names:
        if stop() is not None:
            exit_code = 130
            break
        if os_.game_running():
            print("verify: the game is running; close it first", file=sys.stderr)
            exit_code = 2
            break
        print(f"=== {name} ===", flush=True)
        code = _launch_worker(os_, out, source, staged, game, name, hours, preset, stop)
        result_path = out / f"{name}.result.json"
        if result_path.exists():
            row = json.loads(result_path.read_bytes())
        else:
            worker_log = out / f"{name}.worker.log"
            reason = worker_log.read_text(encoding="utf-8", errors="replace").strip()
            row = {"scenario": name, "verdict": "FAIL", "exit": code, "reason": reason or "no worker result"}
            result_path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        rows.append(row)
        print(f"  {row['verdict']}: {row['reason']}" if row["reason"] else f"  {row['verdict']}")
        if (verdict := out / f"{name}.verdict.log").is_file():
            print(verdict.read_text(encoding="utf-8"), end="")
        if code == 130 or stop() is not None:
            exit_code = 130
            break
        if code not in {0, 1} or os_.game_running():
            exit_code = 2 if code not in {0, 1} else 1
            break
        if row["verdict"] != "PASS":
            exit_code = 1
    summary = {"build_sha256": info.result_sha256, "rows": rows}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _print_summary(rows)
    if keep or exit_code:
        print(f"verify: {'FAIL' if exit_code else 'PASS'}; sandbox kept at {out / 'sandbox'}")
    else:
        shutil.rmtree(out / "sandbox")
        print("verify: PASS")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_worker"]:
        return _worker(argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scenario", action="append", choices=BOUNDED_SCENARIOS, help="one bounded scenario (repeatable)")
    mode.add_argument("--all", action="store_true", help="all bounded scenarios (not the soak)")
    mode.add_argument("--soak", type=_hours, metavar="HOURS", help="run a Linux soak")
    parser.add_argument("--soak-preset", type=Path, metavar="JSON", help="override the built-in night preset")
    parser.add_argument("--candidate-dir", type=Path, metavar="DIR", help="read a built patch and its app metadata from DIR")
    parser.add_argument("--keep", action="store_true", help="retain sandbox profiles even on success")
    args = parser.parse_args(argv)
    if args.soak is None and args.soak_preset is not None:
        parser.error("--soak-preset requires --soak")
    names = ("soak",) if args.soak is not None else BOUNDED_SCENARIOS if args.all else tuple(dict.fromkeys(args.scenario))
    out = None
    try:
        os_ = platform.current()
        for name in names:
            check_supported(os_, name)
        source = find_profile(os_.godot_user_data_root()).absolute()
        real_app = os_.app_data_dir().resolve()
        candidate = (args.candidate_dir or patch_info.farmer_dir(os_)).resolve()
        preset = args.soak_preset.resolve(strict=True) if args.soak_preset else None
        game = os_.game_executable().absolute()
        if not game.is_file() or not os.access(game, os.X_OK):
            raise ValueError(f"game not found or not executable at {game}")
        root = (Path.cwd() / ".sandbox").resolve()
        local_lock = root / "verify.lock"  # Queue with legacy verify.sh until cutover.
        user_lock = Path.home() / ".midgard-farm-verify.lock"  # Queue across checkouts for this operator.
        if (local_lock.is_symlink() or user_lock.is_symlink()
                or any(p.is_relative_to(real) for p in (root, user_lock.resolve())
                       for real in (source.resolve(), real_app, candidate))):
            raise ValueError("verification storage overlaps the source profile or app data")
        seconds = float(os.environ.get("VERIFY_LOCK_WAIT", "3600"))
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("VERIFY_LOCK_WAIT must be a finite, nonnegative number of seconds")
        root.mkdir(exist_ok=True)
        deadline = time.monotonic() + seconds
        with (shutdown_request() as stop, wait_for_lock(os_, user_lock, deadline, stop),
              wait_for_lock(os_, local_lock, deadline, stop)):
            if os_.game_running():
                raise ValueError("the game is running; close it first (verification never touches the real profile)")
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            out = Path(tempfile.mkdtemp(dir=root, prefix=f"verify-{stamp}-"))
            return _suite(os_, out, source, candidate, game, names, hours=args.soak or 0.0,
                          preset=preset, keep=args.keep, stop=stop)
    except InterruptedError as exc:
        print(f"verify: {exc}", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, ProfileNotFound, patch_info.PatchInfoError) as exc:
        print(f"verify: {exc}", file=sys.stderr)
        if out is not None:
            print(f"verify: artifacts {out}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
