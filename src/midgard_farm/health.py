"""Is the farm making progress? `python -m midgard_farm.health [--seconds N]`

Samples the farmer's status file twice and compares the run's own time. A fresh
heartbeat in phase `run` is not enough: on 2026-11-19 the run sat at t=640 for
6.5 h with a healthy heartbeat. Works for the legacy farmer and the app alike;
it only reads the profile's `farmer_status.json`.

Exit codes: 0 farming / between runs / paused / finished, 1 stalled,
2 not running (no status, or the heartbeat is old).
"""

import argparse
import enum
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import platform
from .core.profile import ProfileNotFound, find_profile

STATUS_FILE = "farmer_status.json"
# The farmer refreshes its heartbeat every few seconds; a supervisor treats
# 3 missed 5 s beats as dead.
HEARTBEAT_STALE_SECONDS = 30.0
BETWEEN_RUNS = ("settle", "keep", "maint", "idle")
FINISHED = ("done", "failed")


class Verdict(enum.Enum):
    FARMING = "farming"
    BETWEEN_RUNS = "between runs"
    PAUSED = "paused"
    FINISHED = "finished"
    STALLED = "stalled"
    NOT_RUNNING = "not running"


EXIT_CODES = {Verdict.STALLED: 1, Verdict.NOT_RUNNING: 2}


@dataclass(frozen=True)
class Health:
    kind: Verdict
    message: str

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.kind, 0)


def _number(status: dict, *keys: str) -> float:
    value: object = status
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return float(value) if isinstance(value, (int, float)) else 0.0


def judge(first: dict | None, second: dict | None, *, seconds: float, now: float) -> Health:
    """Classify two status samples taken `seconds` apart; `now` is the second's time."""
    if second is None:
        return Health(Verdict.NOT_RUNNING, f"NOT RUNNING: no readable {STATUS_FILE}")
    phase = str(second.get("phase", ""))
    if phase in FINISHED:
        return Health(Verdict.FINISHED, f"FINISHED: session ended ({phase}), "
                      f"{int(_number(second, 'totals', 'runs'))} runs")
    age = now - _number(second, "heartbeat")
    if age > HEARTBEAT_STALE_SECONDS:
        return Health(Verdict.NOT_RUNNING, f"NOT RUNNING: last heartbeat {age:.0f} s ago (phase {phase or '?'})")
    if phase == "paused":
        return Health(Verdict.PAUSED, "PAUSED: paused by the operator")
    if phase != "run" or first is None or first.get("phase") != "run":
        return Health(Verdict.BETWEEN_RUNS, f"BETWEEN RUNS: phase {phase or '?'}, "
                      f"{int(_number(second, 'totals', 'runs'))} runs so far")
    t0, t1 = _number(first, "game", "time"), _number(second, "game", "time")
    kills = int(_number(second, "game", "kills") - _number(first, "game", "kills"))
    if t1 <= t0:
        return Health(Verdict.STALLED, f"STALLED: run time stuck at t={t1:.0f} for {seconds:g} s "
                      f"despite a fresh heartbeat ({kills:+d} kills)")
    zeny = int(_number(second, "totals", "zeny") - _number(first, "totals", "zeny"))
    return Health(Verdict.FARMING, f"FARMING: t {t0:.0f} -> {t1:.0f} in {seconds:g} s, "
                  f"{kills:+d} kills, {zeny:+,d} zeny, {int(_number(second, 'totals', 'runs'))} runs done")


def _sample(os_: platform.Platform, path: Path) -> dict | None:
    try:
        data = json.loads(os_.read_shared(path))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m midgard_farm.health", description=__doc__.split("\n")[0])
    parser.add_argument("--seconds", type=float, default=15.0, help="time between the two samples (default 15)")
    parser.add_argument("--profile", type=Path, help="profile directory (default: the discovered game profile)")
    args = parser.parse_args(argv)
    os_ = platform.current()
    try:
        profile = args.profile or find_profile(os_.godot_user_data_root())
    except ProfileNotFound as exc:
        print(f"NOT RUNNING: {exc}")
        return EXIT_CODES[Verdict.NOT_RUNNING]
    path = profile / STATUS_FILE
    first = _sample(os_, path)
    time.sleep(args.seconds)
    health = judge(first, _sample(os_, path), seconds=args.seconds, now=time.time())
    print(health.message)
    return health.exit_code


if __name__ == "__main__":
    sys.exit(main())
