"""Atomic, periodically refreshed service state for the window's file poller."""

import json
import math
import threading
import time
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any, TypedDict, Unpack

from ..platform import Platform

REFRESH_INTERVAL = 1.0
STALE_INTERVALS = 3
_FUTURE_INTERVALS = 2
_MIN_REFRESH_INTERVAL = 0.1
_MAX_REFRESH_INTERVAL = 10.0


class StateKind(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    WAITING_FOR_GAME = "waiting_for_game"
    REBUILDING = "rebuilding"
    UPDATING = "updating"
    FARMER_UNAVAILABLE = "farmer_unavailable"
    STALE = "stale"  # Reader-only: the service is not publishing.


@dataclass(frozen=True)
class ServiceState:
    kind: StateKind
    reason: str
    updated_at: float | None = None  # Service publication time (Unix seconds).
    refresh_interval: float = REFRESH_INTERVAL
    session_id: str | None = None
    farmer_phase: str | None = None
    last_heartbeat: float | None = None  # Farmer heartbeat, not service liveness.
    last_outcome: dict[str, Any] | None = None
    quarantine: dict[str, Any] | None = None
    command_refusals: tuple[dict[str, Any], ...] = ()
    refusals_superseded_through: str = ""
    game_update_classification: str | None = None
    last_restore: dict[str, Any] | None = None
    keep_official: bool = False


class _PatchChanges(TypedDict, total=False):
    game_update_classification: str
    last_restore: dict[str, Any]
    keep_official: bool


class _StateChanges(TypedDict, total=False):
    session_id: str | None
    farmer_phase: str | None
    last_heartbeat: float | None
    last_outcome: dict[str, Any] | None
    quarantine: dict[str, Any] | None
    refusals_superseded_through: str


def state_path(os_: Platform) -> Path:
    return os_.app_data_dir() / "state.json"


def _object(os_: Platform, path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(os_.read_shared(path))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return float(value) if math.isfinite(value) else None
        except OverflowError:
            pass
    return None


def _refresh_interval(value: object) -> float:
    interval = _number(value)
    if interval is None:
        return REFRESH_INTERVAL
    return min(_MAX_REFRESH_INTERVAL, max(_MIN_REFRESH_INTERVAL, interval))


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def read_state(os_: Platform) -> ServiceState:
    """Classify missing, unreadable or expired state as stale, keeping readable diagnostics."""
    payload = _object(os_, state_path(os_)) or {}
    updated_at = _number(payload.get("updated_at"))
    interval = _refresh_interval(payload.get("refresh_interval"))
    reason = _text(payload.get("reason")) or ""
    try:
        kind = StateKind(_text(payload.get("kind")) or "")
    except ValueError:
        kind = StateKind.STALE
    if (kind is StateKind.STALE or updated_at is None
            or not -_FUTURE_INTERVALS * interval <= time.time() - updated_at <= STALE_INTERVALS * interval):
        kind, reason = StateKind.STALE, "Service is not running"
    outcome, quarantine = payload.get("last_outcome"), payload.get("quarantine")
    refusals = payload.get("command_refusals")
    restore = payload.get("last_restore")
    return ServiceState(kind, reason, updated_at, interval, _text(payload.get("session_id")),
                        _text(payload.get("farmer_phase")), _number(payload.get("last_heartbeat")),
                        outcome if isinstance(outcome, dict) else None,
                        quarantine if isinstance(quarantine, dict) else None,
                        tuple(row for row in refusals if isinstance(row, dict)) if isinstance(refusals, list) else (),
                        _text(payload.get("refusals_superseded_through")) or "",
                        _text(payload.get("game_update_classification")),
                        restore if isinstance(restore, dict) else None, payload.get("keep_official") is True)


def _quarantine(record: dict[str, Any]) -> dict[str, Any]:
    reason = record.get("reason")
    action = ("Check again" if reason in ("build_failed", "anchors_broken", "smoke_failed")
              else "Start a new session")
    return {**record, "detail": record.get("detail") or record.get("last_failure") or reason,
            "next_action": record.get("next_action") or action}


class StateReporter:
    """One publisher under the service lock; refreshes even during blocking work."""

    def __init__(self, os_: Platform, *, refresh_interval: float = REFRESH_INTERVAL):
        self._os = os_
        self._path = state_path(os_)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._error: str | None = None
        previous = read_state(os_)
        quarantine = _object(os_, self._path.parent / "quarantine.json") or previous.quarantine
        self._state = ServiceState(StateKind.IDLE, "", refresh_interval=_refresh_interval(refresh_interval),
                                   last_heartbeat=previous.last_heartbeat,
                                   last_outcome=previous.last_outcome,
                                   quarantine=_quarantine(quarantine) if quarantine is not None else None,
                                   command_refusals=self._read_refusals(previous.refusals_superseded_through),
                                   refusals_superseded_through=previous.refusals_superseded_through,
                                   game_update_classification=previous.game_update_classification,
                                   last_restore=previous.last_restore, keep_official=previous.keep_official)
        self._thread = threading.Thread(target=self._refresh, daemon=True)

    def __enter__(self) -> "StateReporter":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._publish()
        self._thread.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self._stop.set()
        self._thread.join()

    def set(self, kind: StateKind, reason: str = "", **changes: Unpack[_StateChanges]) -> None:
        """Publish a transition immediately; fields not supplied remain unchanged."""
        if (quarantine := changes.get("quarantine")) is not None:
            changes["quarantine"] = _quarantine(quarantine)
        with self._lock:
            prior_cutoff = self._state.refusals_superseded_through
            updated = replace(self._state, kind=kind, reason=reason, **changes)
            if updated == self._state and self._error is None:
                return
            self._state = updated
            if (cutoff := self._state.refusals_superseded_through) != prior_cutoff:
                self._state = replace(self._state, command_refusals=self._read_refusals(cutoff))
            self._publish()

    def patch_status(self, **changes: Unpack[_PatchChanges]) -> None:
        """Publish patch diagnostics without changing the session or service phase."""
        with self._lock:
            updated = replace(self._state, **changes)
            if updated != self._state or self._error is not None:
                self._state = updated
                self._publish()

    def observe_farmer(self, status: dict[str, Any]) -> None:
        phase = _text(status.get("phase"))
        heartbeat = _number(status.get("heartbeat"))
        with self._lock:
            phase_changed = phase != self._state.farmer_phase
            self._state = replace(self._state, farmer_phase=phase,
                                  last_heartbeat=heartbeat if heartbeat is not None else self._state.last_heartbeat)
            if phase_changed:
                self._publish()

    def refusals_changed(self) -> None:
        with self._lock:
            refusals = self._read_refusals(self._state.refusals_superseded_through)
            self._state = replace(self._state, command_refusals=refusals)
            self._publish()

    def _read_refusals(self, cutoff: str) -> tuple[dict[str, Any], ...]:
        return tuple({**record, "request": path.name}
                     for path in sorted((self._path.parent / "command-rejections").glob("*.json"), reverse=True)[:20]
                     if path.name > cutoff and (record := _object(self._os, path)) is not None)

    def _refresh(self) -> None:
        while not self._stop.wait(self._state.refresh_interval):
            with self._lock:
                self._publish()

    def _publish(self) -> None:
        try:
            self._os.write_atomic(self._path, json.dumps({"v": 1, **asdict(self._state),
                                                          "updated_at": time.time()}).encode())
            self._error = None
        except OSError as exc:
            if str(exc) != self._error:
                self._error = str(exc)
                print(f"supervisor: could not publish service state: {exc}", flush=True)
