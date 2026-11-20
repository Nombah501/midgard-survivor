"""Is the farm making progress? `python -m midgard_farm.health [--seconds N]`

Samples the farmer's status file twice and compares the run's own time. A fresh
heartbeat is not proof of progress. When available, the supervisor's progress
clock tells how long the current run has been frozen. Works read-only with the
legacy farmer too, but without supervisor evidence.

Exit codes: 0 progressing / watching / between runs / paused / finished,
1 stalled, 2 not running (no status, or the heartbeat is old).
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
from .core.run_progress import HEARTBEAT_STALE_AFTER, Progress, RunProgress, published_progress
from .core.state import ServiceState, StateKind, read_state

STATUS_FILE = "farmer_status.json"
FINISHED = ("done", "failed")


class Verdict(enum.Enum):
    PROGRESSING = "progressing"
    WATCHING = "watching"
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


def judge(first: dict | None, second: dict | None, *, seconds: float, now: float,
          state: ServiceState | None = None, monotonic_now: float | None = None) -> Health:
    """Classify two samples; `now` and `monotonic_now` are the second sample's clocks."""
    if second is None:
        return Health(Verdict.NOT_RUNNING, f"NOT RUNNING: no readable {STATUS_FILE}")
    phase = str(second.get("phase", ""))
    if phase in FINISHED:
        return Health(Verdict.FINISHED, f"FINISHED: session ended ({phase}), "
                      f"{int(_number(second, 'totals', 'runs'))} runs")
    if (state is not None and (state.kind is not StateKind.ACTIVE or not state.session_id
                               or state.session_id != second.get("session"))):
        state = None
    stale_after = state.heartbeat_stale_after if state is not None else None
    age = now - _number(second, "heartbeat")
    if age > (stale_after if stale_after is not None else HEARTBEAT_STALE_AFTER):
        return Health(Verdict.NOT_RUNNING, f"NOT RUNNING: last heartbeat {age:.0f} s ago (phase {phase or '?'})")
    if phase == "paused":
        return Health(Verdict.PAUSED, "PAUSED: paused by the operator")
    if phase != "run":
        return Health(Verdict.BETWEEN_RUNS, f"BETWEEN RUNS: phase {phase or '?'}, "
                      f"{int(_number(second, 'totals', 'runs'))} runs so far")
    tracker = RunProgress()
    tracker.observe(first, 0)
    progress = tracker.observe(second, seconds)
    known = None
    if state is not None and state.farmer_phase == "run" and state.run_progress is not None:
        known = published_progress(second, state.run_progress, wall_now=now,
                                   now=time.monotonic() if monotonic_now is None else monotonic_now)
    note = "" if known is not None else " (unconfirmed by supervisor)"
    t1 = _number(second, "game", "time")
    if progress is Progress.ADVANCING and first is not None and (known is None or not known[1]):
        t0 = _number(first, "game", "time")
        kills = int(_number(second, "game", "kills") - _number(first, "game", "kills"))
        zeny = int(_number(second, "totals", "zeny") - _number(first, "totals", "zeny"))
        return Health(Verdict.PROGRESSING, f"PROGRESSING: t {t0:.0f} -> {t1:.0f} in {seconds:.3g} s, "
                      f"{kills:+d} kills, {zeny:+,d} zeny, {int(_number(second, 'totals', 'runs'))} runs done{note}")
    if known is not None:
        age, stalled = known
    elif progress is not None:
        age, stalled = seconds, progress is Progress.STALLED
    else:
        return Health(Verdict.WATCHING, f"WATCHING: waiting for a comparable run time sample{note}")
    kind = Verdict.STALLED if stalled else Verdict.WATCHING
    return Health(kind, f"{kind.value.upper()}: run time has not advanced from t={t1:.0f} for {age:.3g} s "
                        f"despite a fresh heartbeat{note}")


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
    health = judge(None, first, seconds=0, now=time.time(), state=read_state(os_))
    if health.kind is Verdict.STALLED:
        print(health.message)
        return health.exit_code
    started = time.monotonic()
    time.sleep(args.seconds)
    second = _sample(os_, path)
    elapsed = time.monotonic() - started
    state = read_state(os_)
    health = judge(first, second, seconds=elapsed, now=time.time(), state=state)
    print(health.message)
    return health.exit_code


if __name__ == "__main__":
    sys.exit(main())
