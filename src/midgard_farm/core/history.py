"""Append-only session and update history. Add fields without changing v1 meanings."""

import json
import math
import os
import time
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, time as local_time, timedelta
from pathlib import Path
from typing import Any

from ..platform import Platform


def history_path(os_: Platform) -> Path:
    return os_.app_data_dir() / "history.jsonl"


def append_event(os_: Platform, kind: str, **fields: Any) -> None:
    """Append a session, game_update or app_update record; caller holds the service lock."""
    path = history_path(os_)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": time.time(), **fields, "v": 1, "kind": kind}
    line = json.dumps(record, allow_nan=False).encode() + b"\n"
    with path.open("a+b") as file:
        if file.tell():
            file.seek(-1, os.SEEK_END)
            if file.read(1) != b"\n":  # A process may have died while appending.
                line = b"\n" + line
        file.write(line)
        file.flush()
        os.fsync(file.fileno())


def _rows(raw: bytes) -> Iterator[dict[str, Any]]:
    for line in raw.split(b"\n"):
        if line.strip():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def read_history(os_: Platform) -> list[dict[str, Any]]:
    """Read v1 session/update rows in append order, tolerating unknown fields and torn lines."""
    try:
        raw = os_.read_shared(history_path(os_))
    except FileNotFoundError:
        return []
    return [row for row in _rows(raw) if type(row.get("v")) is int and row["v"] == 1
            and row.get("kind") in ("session", "game_update", "app_update")
            and type(row.get("timestamp")) in (int, float)]


def read_run_journal(os_: Platform, path: Path) -> Iterator[dict[str, Any]]:
    """Read farmer run rows in append order using a Windows-compatible shared read."""
    try:
        return _rows(os_.read_shared(path))
    except FileNotFoundError:
        return iter(())


def _finite_number(value: object) -> int | float | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return value if isinstance(value, float) and math.isfinite(value) else None


def _number(value: object) -> int | float:
    return _finite_number(value) or 0


@dataclass(frozen=True)
class SessionTiming:
    elapsed_s: float | None
    run_s: float | None

    @property
    def downtime_s(self) -> float | None:
        if self.elapsed_s is None or self.run_s is None:
            return None
        return max(0, self.elapsed_s - self.run_s)


def session_timing(row: dict[str, Any]) -> SessionTiming:
    """Read session elapsed time separately from the journal's settled-run time."""
    start, end = _finite_number(row.get("started_at")), _finite_number(row.get("timestamp"))
    totals = row.get("totals")
    run_s = _finite_number(totals.get("wall_s")) if isinstance(totals, dict) else None
    elapsed = end - start if start is not None and end is not None and end >= start else None
    return SessionTiming(elapsed, run_s if run_s is not None and run_s >= 0 else None)


@dataclass(frozen=True)
class NightSummary:
    sessions: int
    zeny: int | float | None
    wins: int | float | None
    runs: int | float | None
    downtime_s: float | None
    partial_downtime: bool


def night_summary(rows: Iterable[dict[str, Any]], today: date,
                  active: dict[str, Any] | None = None) -> NightSummary:
    """Sum whole overlapping sessions; the journal cannot cut rewards at clock boundaries."""
    start = datetime.combine(today - timedelta(days=1), local_time(18)).timestamp()
    end = datetime.combine(today, local_time(12)).timestamp()
    sessions = timed = 0
    amounts: dict[str, int | float | None] = dict.fromkeys(("zeny", "wins", "runs"), 0)
    downtime = 0.0

    def include(row: dict[str, Any], *, ongoing: bool = False) -> None:
        nonlocal sessions, timed, downtime
        if (finished := _finite_number(row.get("timestamp"))) is None:
            return
        began = _finite_number(row.get("started_at"))
        if began is None or began > finished:
            # For old rows without a start, only the completion time proves membership.
            if not start <= finished < end:
                return
        elif not (finished > start and began < end):
            return
        sessions += 1
        totals = row.get("totals")
        for key, previous in amounts.items():
            amount = _finite_number(totals.get(key)) if isinstance(totals, dict) else None
            amounts[key] = previous + amount if previous is not None and amount is not None else None
        # The active session's unsettled run time is not downtime.
        if not ongoing and (idle := session_timing(row).downtime_s) is not None:
            downtime += idle
            timed += 1

    active_id = active.get("session_id") if active is not None else None
    for row in rows:
        if row.get("kind") == "session":
            include(row)
            if active_id is not None and row.get("session_id") == active_id:
                active = None  # State may lag the committed terminal history row.
    if active is not None:
        include(active, ongoing=True)
    return NightSummary(sessions, amounts["zeny"], amounts["wins"], amounts["runs"],
                        downtime if timed else None, timed < sessions)


_REWARDS = {"zeny": "zeny_gain", "xp": "xp_gain", "kills": "kills", "coins": "coins_gain", "ymir": "ymir_gain"}


def session_summary(os_: Platform, profile: Path, session_id: str,
                    status_totals: dict[str, Any]) -> dict[str, Any]:
    """Collect cumulative totals and the actual run choices from the journal."""
    try:
        rows = read_run_journal(os_, profile / "farmer_runs.jsonl")
    except OSError as exc:
        print(f"supervisor: could not read totals from farmer journal: {exc}", flush=True)
        rows = iter(())

    seen: set[str] = set()
    materials: Counter[str] = Counter()
    rewards: Counter[str] = Counter()
    runs = wins = cards = 0
    choices: list[dict[str, Any]] = []
    wall_s = 0.0
    for row in rows:
        if row.get("session") != session_id:
            continue
        if isinstance(run_id := row.get("run_id"), str) and run_id:
            if run_id in seen:
                continue
            seen.add(run_id)
            stage, danger = row.get("stage"), _number(row.get("danger"))
            if isinstance(stage, str) and stage and danger:
                choice = {"run_id": run_id, "stage": stage, "danger": int(danger)}
                if "oath_points" in row:
                    choice["oath_points"] = int(_number(row["oath_points"]))
                for key in ("kept", "keep_skipped"):
                    if isinstance(items := row.get(key), list) and items:
                        choice[key] = items
                if isinstance(falls := row.get("falls_by_mechanic"), dict):
                    choice["falls_by_mechanic"] = falls
                choices.append(choice)
        runs += 1
        wins += row.get("victory") is True
        wall_s += _number(row.get("wall_s"))
        cards += int(_number(row.get("cards_gain")))
        for target, source in _REWARDS.items():
            rewards[target] += int(_number(row.get(source)))
        if isinstance(delta := row.get("materials"), dict):
            materials.update({key: int(_number(value)) for key, value in delta.items()})

    if not runs and isinstance(delta := status_totals.get("materials"), dict):
        materials.update({key: int(_number(value)) for key, value in delta.items()})
    # A run may have reached the journal after the last heartbeat, immediately before a crash.
    accounted = _number(status_totals.get("runs")) >= runs
    tallies = {"runs": runs, "wins": wins, "losses": runs - wins,
               **{name: rewards[name] for name in _REWARDS}}
    totals = {**{key: _number(status_totals[key]) if accounted and key in status_totals else value
                 for key, value in tallies.items()},
              "started": max(runs, _number(status_totals.get("started"))),
              "lost": _number(status_totals.get("lost")), "wall_s": wall_s, "cards_gain": cards,
              "materials": dict(materials)}
    return {"totals": totals, "run_choices": choices}
