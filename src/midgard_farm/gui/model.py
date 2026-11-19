"""Display-independent AFK session view of the service's file interface."""

import json
import math
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core import commands
from ..core.history import read_history
from ..core.profile import ProfileNotFound, find_profile
from ..core.state import ServiceState, StateKind, read_state
from ..platform import Platform


@dataclass(frozen=True)
class _Preset:
    path: Path
    fixed: commands.Character | None
    description: str


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _object(os_: Platform, path: Path) -> dict[str, Any]:
    try:
        return _mapping(json.loads(os_.read_shared(path)))
    except (OSError, ValueError, RecursionError):
        return {}


def _character(class_id: object, job_path: object) -> commands.Character | None:
    if isinstance(class_id, str) and class_id and type(job_path) is int and job_path >= 0:
        return commands.Character(class_id, job_path)
    return None


def _catalog(os_: Platform) -> tuple[dict[commands.Character, str], list[_Preset], dict[str, str]]:
    # Ticket 11 will bundle the farmer assets. Until then both catalogs live in the checkout.
    assets = Path(__file__).resolve().parents[3] / "farmer"
    targets = _object(os_, assets / "targets.json")
    characters: dict[commands.Character, str] = {}
    for value in _mapping(targets.get("characters")).values():
        row = _mapping(value)
        character = _character(row.get("class"), row.get("job_path"))
        if character and isinstance(label := row.get("label"), str):
            characters[character] = label
    stages = {key: value for key, value in _mapping(targets.get("stages")).items() if isinstance(value, str)}
    presets = []
    for path in sorted((assets / "presets").glob("*.json")):
        if not (data := _object(os_, path)):
            continue
        class_id = data.get("class")
        fixed = _character(class_id, _mapping(data.get("job_paths")).get(class_id, 0)) if isinstance(class_id, str) else None
        stage = data.get("stage")
        location = stages.get(stage, stage) if stage else "Automatic"
        danger = data.get("danger", "Automatic")
        if danger in ("auto", "max") and data.get("danger_ceiling") is not None:
            danger = f"{'Automatic' if danger == 'auto' else 'Maximum'}, up to {data['danger_ceiling']}"
        description = f"Location: {location}  ·  Difficulty: {danger}"
        if fixed:
            description += "  ·  Character fixed by preset"
        presets.append(_Preset(path, fixed, description))
    return characters, presets, stages


_PHASES = {
    "idle": "Between runs",
    "run": "Run in progress",
    "settle": "Settling the run",
    "keep": "Choosing what to keep",
    "maint": "Maintenance",
    "paused": "Paused",
    "done": "Session ending",
    "failed": "Farmer stopped",
}
_DASH = "—"


def _number(value: object) -> int | float | None:
    if type(value) is int:
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _format_number(value: object, decimals: int = 0) -> str:
    number = _number(value)
    return f"{number:,.{decimals}f}" if number is not None else _DASH


def _heartbeat_age(timestamp: float | None) -> str:
    if timestamp is None:
        return _DASH
    seconds = int(max(0, time.time() - timestamp))
    if seconds >= 3600:
        return f"{seconds // 3600} h {seconds % 3600 // 60} min ago"
    if seconds >= 60:
        return f"{seconds // 60} min {seconds % 60} s ago"
    return f"{seconds} s ago"


@dataclass(frozen=True)
class SessionView:
    phase: str = "Reading AFK session…"
    heartbeat_age: str = _DASH
    zeny: str = _DASH
    materials: str = _DASH
    kills: str = _DASH
    current_run: str = _DASH
    run_detail: str = ""
    run_totals: str = _DASH
    session_id: str = ""
    active: bool = False
    paused: bool = False
    can_pause: bool = False
    can_control: bool = False
    characters: list[str] = field(default_factory=list)
    presets: list[str] = field(default_factory=list)
    character_index: int = -1
    preset_index: int = -1
    can_start: bool = False
    can_pick_character: bool = False
    can_pick_preset: bool = False
    preset_description: str = ""
    start_reason: str = ""
    start_refusal: str = ""
    action_error: str = ""
    service_missing: bool = False


class SessionModel:
    def __init__(self, os_: Platform):
        self._os = os_
        self._settings = os_.app_data_dir() / "window-settings.json"
        self._characters, self._presets, self._stages = _catalog(os_)
        saved = _object(os_, self._settings)
        self._character = _character(saved.get("class"), saved.get("job_path"))
        if self._character not in self._characters:
            self._character = next(iter(self._characters), None)
        self._preset = next((p for p in self._presets if p.path.name == saved.get("preset")), None)
        if self._preset is None:
            self._preset = next((p for p in self._presets if p.path.name == "night.json"),
                                self._presets[0] if self._presets else None)
        self._last_start: Path | None = None
        self._pending_start = False
        self._action_error = ""
        self.history: list[dict[str, Any]] = []

    def poll(self) -> SessionView:
        state = read_state(self._os)
        try:
            self.history = read_history(self._os)
        except OSError:
            pass  # Retain the last readable history until the file becomes available.
        status = self._read_status(state)
        quarantine = self._quarantine(state)
        preset = self._preset
        fixed = preset.fixed if preset else None
        selected = fixed or self._character
        options = list(self._characters)
        characters = list(self._characters.values())
        presets = [p.path.name for p in self._presets]
        missing = state.kind is StateKind.STALE
        busy = not missing and (state.session_id is not None or state.kind is StateKind.ACTIVE)
        farmer_phase = state.farmer_phase or ""
        if missing:
            phase = "Service not running"
        elif quarantine:
            phase = "Quarantine"
        elif state.kind is StateKind.ACTIVE:
            phase = _PHASES.get(farmer_phase) or state.reason or "Starting AFK session"
        elif state.kind is StateKind.IDLE:
            phase = "Ready to start"
        else:
            phase = state.kind.value.replace("_", " ").capitalize()
        reason = self._start_blocker(state, busy, selected, quarantine)
        refusal = self._start_refusal(state)
        if self._pending_start and not reason:
            reason = "Start requested; waiting for the service."
        rates = _mapping(status.get("rates"))
        materials = f"{_format_number(rates.get('ore_h'), 1)} / {_format_number(rates.get('crumbs_h'), 1)}"
        totals = _mapping(status.get("totals"))
        run, detail = self._run_text(status, totals)
        can_control = (state.kind is StateKind.ACTIVE and bool(state.session_id)
                       and farmer_phase in ("", "idle", "run", "settle", "keep", "maint", "paused")
                       and status.get("terminal") is not True)
        return SessionView(
            phase=phase, heartbeat_age=_heartbeat_age(state.last_heartbeat),
            zeny=_format_number(rates.get("zeny_h")), materials=materials if rates else _DASH,
            kills=_format_number(rates.get("kills_min"), 1), current_run=run, run_detail=detail,
            run_totals=" · ".join(f"{_format_number(totals.get(key))} {label}"
                                  for key, label in (("runs", "settled"), ("wins", "wins"), ("lost", "lost")))
            if totals else _DASH,
            session_id=state.session_id or "", active=busy, paused=farmer_phase == "paused",
            can_control=can_control, can_pause=can_control and bool(farmer_phase),
            characters=characters, presets=presets,
            character_index=options.index(selected) if selected in options else -1,
            preset_index=self._presets.index(preset) if preset else -1,
            can_start=not reason, can_pick_character=not busy and fixed is None and bool(characters),
            can_pick_preset=not busy and bool(presets), preset_description=preset.description if preset else "",
            start_reason=reason, start_refusal=refusal, action_error=self._action_error, service_missing=missing,
        )

    def _read_status(self, state: ServiceState) -> dict[str, Any]:
        if state.kind is not StateKind.ACTIVE or not state.session_id or not state.farmer_phase:
            return {}
        try:
            profile = find_profile(self._os.godot_user_data_root())
        except (OSError, ProfileNotFound):
            return {}
        status = _object(self._os, profile / "farmer_status.json")
        return status if status.get("session") == state.session_id else {}

    def _run_text(self, status: dict[str, Any], totals: dict[str, Any]) -> tuple[str, str]:
        if status.get("phase") not in ("run", "settle", "keep") or not status.get("run_id"):
            return _DASH, ""
        game = _mapping(status.get("game"))
        target = _mapping(status.get("target"))
        stage = game.get("stage") or target.get("stage")
        started = _number(totals.get("started"))
        parts = [f"Run {started:.0f}" if started else "Run in progress"]
        if isinstance(stage, str):
            parts.append(self._stages.get(stage, stage))
        if danger := _number(game.get("danger")) or _number(target.get("danger")):
            parts.append(f"Difficulty {danger:.0f}")
        detail = []
        if level := _number(game.get("level")):
            detail.append(f"Level {level:.0f}")
        if (elapsed := _number(game.get("time"))) is not None and elapsed >= 0:
            minutes, seconds = divmod(int(elapsed), 60)
            detail.append(f"{minutes:02d}:{seconds:02d}")
        hp, max_hp = _number(game.get("hp")), _number(game.get("max_hp"))
        if hp is not None and max_hp is not None and max_hp > 0:
            detail.append(f"HP {hp / max_hp:.0%}")
        return " · ".join(parts), " · ".join(detail)

    def _quarantine(self, state: ServiceState) -> dict[str, Any]:
        record = state.quarantine or {}
        outcome = state.last_outcome or {}
        session = outcome.get("session")
        if (record and outcome.get("kind") == "quarantined" and isinstance(session, str)
                and re.fullmatch(r"afk-[a-f0-9]{32}", session)):
            path = self._settings.parent / "logs" / f"supervisor-{session}" / "quarantine.json"
            session_record = _object(self._os, path)
            if session_record.get("reason") == record.get("reason"):
                return session_record
        return record

    def _start_refusal(self, state: ServiceState) -> str:
        if self._last_start is not None:
            name = self._last_start.name
            for row in state.command_refusals:
                if row.get("request") == name and row.get("command") == "start":
                    self._pending_start = False
                    return str(row.get("reason") or "The service refused this Start.")
            if name <= state.refusals_superseded_through:
                self._pending_start = False
        return ""

    def _start_blocker(self, state: ServiceState, busy: bool, selected: commands.Character | None,
                       quarantine: dict[str, Any]) -> str:
        if state.kind is StateKind.STALE:
            return "Service not running"
        if quarantine:
            return str(quarantine.get("detail") or quarantine.get("reason") or "Quarantine")
        if busy:
            return "An AFK session is already active."
        if state.kind is not StateKind.IDLE:
            return state.reason or state.kind.value.replace("_", " ").capitalize()
        if self._preset is None:
            return "No presets found."
        if selected not in self._characters:
            return "No character available for this preset."
        return ""

    def select_character(self, index: int) -> None:
        if self.poll().can_pick_character and 0 <= index < len(self._characters):
            self._character = list(self._characters)[index]
            self._save_picks()

    def select_preset(self, index: int) -> None:
        if self.poll().can_pick_preset and 0 <= index < len(self._presets):
            self._preset = self._presets[index]
            self._save_picks()

    def _save_picks(self) -> None:
        choice: dict[str, str | int | None] = {"preset": self._preset.path.name if self._preset else None}
        if self._character is not None:
            choice.update({"class": self._character.class_id, "job_path": self._character.job_path})
        try:
            self._settings.parent.mkdir(parents=True, exist_ok=True)
            self._os.write_atomic(self._settings, json.dumps(choice).encode())
        except OSError as exc:
            self._action_error = f"Could not remember the selection: {exc}"
        else:
            self._action_error = ""

    def _submit(self, command: commands.Command) -> Path | None:
        try:
            request = commands.submit(self._os, command)
        except OSError as exc:
            self._action_error = f"Could not send the command: {exc}"
            return None
        self._action_error = ""
        return request

    def start(self) -> Path | None:
        if not self.poll().can_start or self._preset is None:
            return None
        if character := self._preset.fixed or self._character:
            request = self._submit(commands.Start(character, self._preset.path))
            if request is not None:
                self._last_start = request
                self._pending_start = True
            return request
        return None

    def control(self, action: commands.Control, *, session_id: str) -> Path | None:
        view = self.poll()
        if (not view.can_control or view.session_id != session_id
                or (action in ("pause", "resume") and not view.can_pause)
                or (action == "pause" and view.paused) or (action == "resume" and not view.paused)):
            return None
        return self._submit(action)

    def start_service(self) -> bool:
        if read_state(self._os).kind is not StateKind.STALE:
            return False
        try:
            self._os.start_service()
        except subprocess.CalledProcessError as exc:
            self._action_error = f"Could not start the service: {(exc.stderr or exc.stdout or str(exc)).strip()}"
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._action_error = f"Could not start the service: {exc}"
        else:
            self._action_error = ""
            return True
        return False
