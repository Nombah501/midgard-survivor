"""Track progress using the run's own game time, not the heartbeat."""

import math
from enum import Enum
from typing import TypeGuard

RUN_STALLED = "run_stalled"
RUN_STALL_WINDOW = 180.0
# A provisional limit intended to outlast a normal raid, which may freeze game time.
RAID_STALL_WINDOW = 1200.0
# Both consumers allow three missed five-second farmer heartbeats by default.
HEARTBEAT_INTERVAL = 5.0
STALE_HEARTBEAT_INTERVALS = 3
HEARTBEAT_STALE_AFTER = HEARTBEAT_INTERVAL * STALE_HEARTBEAT_INTERVALS
_CLOCK_EPOCH_TOLERANCE = 1.0
_RunKey = tuple[object, object, object, bool]


class Progress(Enum):
    ADVANCING = "advancing"
    WAITING = "waiting"
    STALLED = "stalled"


def in_raid(game: object) -> bool:
    return isinstance(game, dict) and game.get("in_raid") is True


def _number(value: object) -> TypeGuard[int | float]:
    return type(value) is int or isinstance(value, float) and math.isfinite(value)


def _run_clock(status: dict) -> tuple[_RunKey, int | float] | None:
    if status.get("phase") != "run" or status.get("terminal") is True:
        return None
    game = status.get("game")
    game_time = game.get("time") if isinstance(game, dict) else None
    if not _number(game_time):
        return None
    return (status.get("session"), status.get("run_id"), status.get("pid"), in_raid(game)), game_time


def _stalled(age: float, window: float) -> bool:
    return age >= window


def published_progress(status: dict, snapshot: dict, *, now: float, wall_now: float) -> tuple[float, bool] | None:
    """Read a matching, same-boot observation without aging it by wall time."""
    clock = _run_clock(status)
    if clock is None:
        return None
    (_, run_id, pid, raid), game_time = clock
    if (snapshot.get("run_id") != run_id or snapshot.get("pid") != pid
            or snapshot.get("in_raid") is not raid or snapshot.get("game_time") != game_time):
        return None
    at, window, epoch = snapshot.get("at_monotonic"), snapshot.get("window"), snapshot.get("clock_epoch")
    if not (_number(at) and _number(window) and _number(epoch) and 0 <= at <= now and window >= 0):
        return None
    # Allow sampling jitter and small clock corrections. A larger difference is
    # indistinguishable from another boot until a new heartbeat is observed.
    if abs((wall_now - now) - epoch) > _CLOCK_EPOCH_TOLERANCE:
        return None
    age = now - at
    return age, _stalled(age, window)


class RunProgress:
    def __init__(self, window: float = RUN_STALL_WINDOW, raid_window: float = RAID_STALL_WINDOW):
        self._window = window
        self._raid_window = raid_window
        self._key: _RunKey | None = None
        self._time: int | float = 0
        self._since = 0.0

    def observe(self, status: dict | None, now: float) -> Progress | None:
        """Return None until two comparable run samples have been observed."""
        if status is None:
            return None  # An unreadable sample is not evidence of a phase change or a stall.
        clock = _run_clock(status)
        if clock is None:
            self._key = None
            return None
        key, game_time = clock
        if key != self._key:
            self._key, self._time, self._since = key, game_time, now
            return None
        previous, self._time = self._time, game_time
        if game_time > previous:
            self._since = now
            return Progress.ADVANCING
        return Progress.STALLED if _stalled(now - self._since, self._window_for(key)) else Progress.WAITING

    def snapshot(self, now: float, wall_now: float) -> dict | None:
        """Publish the monotonic timer and a wall-clock anchor for its boot."""
        if self._key is None:
            return None
        _, run_id, pid, raid = self._key
        return {"at_monotonic": self._since, "clock_epoch": wall_now - now,
                "run_id": run_id, "pid": pid, "in_raid": raid,
                "game_time": self._time, "window": self._window_for(self._key)}

    def _window_for(self, key: _RunKey) -> float:
        _, _, _, raid = key
        return self._raid_window if raid else self._window
