"""Append-only session and update history. Add fields without changing v1 meanings."""

import json
import math
import os
import time
from collections import Counter
from collections.abc import Iterator
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


def _number(value: object) -> int | float:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return value if isinstance(value, float) and math.isfinite(value) else 0


_REWARDS = {"zeny": "zeny_gain", "xp": "xp_gain", "kills": "kills", "coins": "coins_gain", "ymir": "ymir_gain"}


def session_summary(os_: Platform, profile: Path, session_id: str,
                    status_totals: dict[str, Any]) -> dict[str, Any]:
    """Collect cumulative totals and the actual run choices from the journal."""
    try:
        rows = _rows(os_.read_shared(profile / "farmer_runs.jsonl"))
    except FileNotFoundError:
        rows = iter(())
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
