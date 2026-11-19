"""Display-independent view of the AFK service's file interface."""

import json
import math
import subprocess
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from ..core import commands, game_update
from ..core.history import read_history
from ..core.profile import ProfileNotFound, find_profile
from ..core.state import ServiceState, StateKind, read_state
from ..core.supervisor import session_log_dir
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
_UPDATE_STATES = {
    "current": ("Current", "The official patch and farmer patch match."),
    "game_update": ("Game update", "A new official patch was detected."),
    "farmer_removed_or_stale": ("Farmer patch removed or stale", "The farmer patch needs to be installed or rebuilt."),
    "game_reinstall": ("Game reinstall", "Open the game: start the game and accept the update."),
}
_UPDATE_FAILURES = {
    "build_failed": "Build failed",
    "anchors_broken": "Anchors broke",
    "smoke_failed": "Smoke failed",
}
_ACTIVITY = {
    StateKind.WAITING_FOR_GAME: "Waiting for the game to close",
    StateKind.REBUILDING: "Rebuilding",
}
_TOTALS = (
    ("runs", "Runs"), ("wins", "Wins"), ("lost", "Lost"), ("wall_s", "Time in runs"),
    ("zeny", "Zeny"), ("xp", "XP"), ("kills", "Kills"), ("cards_gain", "Cards"), ("coins", "Coins"), ("ymir", "Ymir"),
)


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _label(value: object) -> str:
    return _text(value).replace("_", " ").capitalize()


def _app_version() -> str:
    try:
        return version("midgard-farm")
    except PackageNotFoundError:
        # A checkout run from src has not necessarily installed distribution metadata.
        try:
            with (Path(__file__).resolve().parents[3] / "pyproject.toml").open("rb") as file:
                project = _mapping(tomllib.load(file).get("project"))
                return _text(project.get("version")) or "Version unavailable"
        except (OSError, ValueError):
            return "Version unavailable"


def _update_outcome(row: dict[str, Any]) -> str:
    if row.get("action") == "restore_official":
        return ""
    if row.get("outcome") == "ready":
        return "Handled"
    return _UPDATE_FAILURES.get(_text(row.get("reason")), "")


def _number(value: object) -> int | float | None:
    if type(value) is int:
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _format_number(value: object, decimals: int = 0) -> str:
    number = _number(value)
    if isinstance(number, int) and decimals == 0:
        return f"{number:,}"
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
class HistoryRow:
    date: str
    title: str
    summary: str
    session_id: str = ""


@dataclass(frozen=True)
class HistoryMetric:
    label: str
    value: str


@dataclass(frozen=True)
class HistoryView:
    rows: list[HistoryRow] = field(default_factory=list)
    latest_session_id: str = ""
    totals: list[HistoryMetric] = field(default_factory=list)
    rewards: str = ""
    materials: str = ""


@dataclass(frozen=True)
class UpdatesView:
    game_state: str = "Not checked yet"
    game_detail: str = ""
    activity: str = ""
    activity_detail: str = ""
    last_outcome: str = "No outcome yet"
    last_detail: str = ""
    action_blocker: str = "Reading service state…"
    feedback: str = ""
    app_version: str = _DASH


@dataclass(frozen=True)
class QuarantineView:
    reason: str = ""
    detail: str = ""
    action: str = ""
    needs_check_again: bool = False
    can_check_again: bool = False
    attempts: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


def _history_view(rows: list[dict[str, Any]]) -> HistoryView:
    entries: list[HistoryRow] = []
    newest_session = ""
    totals: dict[str, Any] = {}
    for row in sorted(rows, key=lambda row: row["timestamp"], reverse=True):
        try:
            date = datetime.fromtimestamp(row["timestamp"]).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError, OverflowError):
            continue
        match row["kind"]:
            case "session":
                session = _text(row.get("session_id"))
                quantities = _mapping(row.get("totals"))
                if session and not newest_session:
                    newest_session, totals = session, quantities
                summary = [f"{_format_number(quantities.get(key))} {label}"
                           for key, label in (("runs", "runs"), ("wins", "wins"), ("zeny", "zeny"))]
                if reason := _label(row.get("reason")):
                    summary.append(reason)
                entries.append(HistoryRow(date, f"AFK session · {_label(row.get('outcome')) or _DASH}",
                                          " · ".join(summary), session))
            case "game_update":
                if row.get("action") == "restore_official":
                    title = "Official patch restored" if row.get("outcome") == "restored" else "Restore official patch"
                else:
                    title = _UPDATE_STATES.get(_text(row.get("classification")), ("Game update", ""))[0]
                    if outcome := _update_outcome(row):
                        title += f" · {outcome}"
                entries.append(HistoryRow(date, title, _text(row.get("detail")) or _text(row.get("reason"))))
            case "app_update":
                outcome = _label(row.get("outcome"))
                title = f"App update · {outcome}" if outcome else "App update"
                entries.append(HistoryRow(date, title, _text(row.get("detail")) or _text(row.get("reason"))))

    if not newest_session:
        return HistoryView(rows=entries)
    seconds = _number(totals.get("wall_s"))
    hours = seconds / 3600 if seconds is not None else None
    metrics = [HistoryMetric(label, (_format_number(hours, 1) + " h" if hours is not None else _DASH)
                             if key == "wall_s" else _format_number(totals.get(key))) for key, label in _TOTALS]
    rewards = " · ".join(f"{_format_number(value / hours)} {label}"
                         for key, label in (("zeny", "zeny"), ("xp", "XP"), ("coins", "coins"),
                                            ("ymir", "Ymir"), ("cards_gain", "cards"))
                         if hours and hours > 0 and (value := _number(totals.get(key))) is not None) or _DASH
    materials = [(key, count) for key, value in _mapping(totals.get("materials")).items()
                 if (count := _number(value)) is not None and count != 0]
    return HistoryView(entries, newest_session, metrics, rewards,
                       " · ".join(f"{key.replace('_', ' ').title()} {_format_number(count)}"
                                  for key, count in sorted(materials, key=lambda entry: (-entry[1], entry[0]))) or _DASH)


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
    history: HistoryView = field(default_factory=HistoryView)
    updates: UpdatesView = field(default_factory=UpdatesView)
    quarantine: QuarantineView = field(default_factory=QuarantineView)


class SessionModel:
    def __init__(self, os_: Platform):
        self._os = os_
        self._settings = os_.app_data_dir() / "window-settings.json"
        self._characters, self._presets, self._stages = _catalog(os_)
        saved = _object(os_, self._settings)
        self._character = _character(saved.get("class"), saved.get("job_path"))
        if ("class" not in saved or saved["class"] is not None) and self._character not in self._characters:
            self._character = next(iter(self._characters), None)
        self._preset = next((p for p in self._presets if p.path.name == saved.get("preset")), None)
        if self._preset is None:
            self._preset = next((p for p in self._presets if p.path.name == "night.json"),
                                self._presets[0] if self._presets else None)
        self._last_start: Path | None = None
        self._pending_start = False
        self._action_error = ""
        self._patch_request: tuple[commands.PatchCommand, Path] | None = None
        self._app_version = _app_version()
        self._history_rows: list[dict[str, Any]] = []
        self._history = HistoryView()
        self._last_update: tuple[str, str] = ("No outcome yet", "")

    def poll(self) -> SessionView:
        state = read_state(self._os)
        self._refresh_history()
        status = self._read_status(state)
        preset = self._preset
        fixed = preset.fixed if preset else None
        selected = fixed or self._character
        options = [*self._characters, None]
        characters = [*self._characters.values(), "Preset decides"]
        presets = [p.path.name for p in self._presets]
        missing = state.kind is StateKind.STALE
        busy = not missing and (state.session_id is not None or state.kind is StateKind.ACTIVE)
        updates = self._updates(state, busy)
        quarantine = self._quarantine(state, not updates.action_blocker)
        farmer_phase = state.farmer_phase or ""
        if missing:
            phase = "Service not running"
        elif quarantine.reason:
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
            history=self._history, updates=updates, quarantine=quarantine,
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

    def _quarantine(self, state: ServiceState, can_check_again: bool) -> QuarantineView:
        record = state.quarantine
        if not record:
            return QuarantineView()
        outcome = state.last_outcome or {}
        paths: list[str] = []
        reason = _text(record.get("reason"))
        diagnostics = _text(record.get("diagnostics"))
        retry = reason in _UPDATE_FAILURES
        session = outcome.get("session")
        if outcome.get("kind") == "quarantined" and isinstance(session, str):
            try:
                directory = session_log_dir(self._os, session)
            except ValueError:
                pass
            else:
                relative = directory.relative_to(self._os.app_data_dir()).as_posix()
                if diagnostics == relative or (not diagnostics and not retry):
                    saved = _object(self._os, directory / "quarantine.json")
                    if saved and saved.get("reason") == reason:
                        record = record | saved
                        try:
                            paths.extend(str(path) for path in sorted(directory.iterdir()) if path.is_file())
                        except OSError:
                            paths.append(str(directory))
        if not paths and diagnostics:
            paths.append(str(self._os.app_data_dir() / diagnostics))
        if log := _text(record.get("log_path")):
            if log not in paths:
                paths.append(log)
        attempts = []
        if isinstance(values := record.get("attempts"), list):
            for entry in values:
                item = _mapping(entry)
                if type(number := item.get("number")) is int:
                    attempts.append(" · ".join(part for part in
                                               (f"Attempt {number}", _label(item.get("outcome")),
                                                _text(item.get("reason"))) if part))
        detail = (_text(record.get("detail")) or _text(record.get("last_failure"))).strip()
        return QuarantineView(_UPDATE_FAILURES.get(reason, _label(reason)) or "Unknown reason",
                              detail.splitlines()[0] if detail else "No additional detail.",
                              "Check again" if retry else "Start a new session", retry,
                              retry and can_check_again, attempts, paths)

    def _refresh_history(self) -> None:
        try:
            rows = read_history(self._os)
        except OSError:
            return  # Retain the last readable history until the file becomes available.
        if rows != self._history_rows:
            self._history_rows = rows
            self._history = _history_view(rows)
            latest = max((row for row in rows if row["kind"] == "game_update" and _update_outcome(row)),
                         key=lambda row: row["timestamp"], default=None)
            self._last_update = (_update_outcome(latest), _text(latest.get("detail"))) if latest else ("No outcome yet", "")

    def _updates(self, state: ServiceState, busy: bool) -> UpdatesView:
        classification = state.game_update_classification
        if state.reason == game_update.START_GAME_AND_UPDATE:
            classification = "game_reinstall"
        title, detail = _UPDATE_STATES.get(classification or "", ("Not checked yet", ""))
        if state.keep_official and classification not in (None, "game_reinstall"):
            detail = "The official patch will stay mounted until Start or Check again."
        activity = _ACTIVITY.get(state.kind, "")
        activity_detail = state.reason if activity and state.reason.casefold() != activity.casefold() else ""
        if state.kind is StateKind.FARMER_UNAVAILABLE and classification != "game_reinstall" and not state.quarantine:
            activity_detail = state.reason
        blocker = ""
        if state.kind is StateKind.STALE:
            blocker = "Service not running."
        elif busy:
            blocker = "An AFK session is already active."
        elif state.kind in (StateKind.REBUILDING, StateKind.UPDATING):
            blocker = "Wait for the current update to finish."
        feedback = ""
        restore = state.last_restore or {}
        if self._patch_request:
            command, request = self._patch_request
            for row in state.command_refusals:
                if row.get("request") == request.name and row.get("command") == command:
                    action = "Restore" if command == "restore_official" else "Check again"
                    feedback = f"{action} refused: {_text(row.get('reason'))}"
                    break
        if not feedback and restore.get("outcome") != "official_patch_missing":
            feedback = _text(restore.get("reason"))
        return UpdatesView(title, detail, activity, activity_detail, *self._last_update, blocker, feedback,
                           self._app_version)

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
                       quarantine: QuarantineView) -> str:
        if state.kind is StateKind.STALE:
            return "Service not running"
        if quarantine.needs_check_again:
            return quarantine.detail
        if busy:
            return "An AFK session is already active."
        if state.kind is not StateKind.IDLE:
            return state.reason or state.kind.value.replace("_", " ").capitalize()
        if self._preset is None:
            return "No presets found."
        if selected is not None and selected not in self._characters:
            return "No character available for this preset."
        return ""

    def select_character(self, index: int) -> None:
        if self.poll().can_pick_character and 0 <= index <= len(self._characters):
            self._character = list(self._characters)[index] if index < len(self._characters) else None
            self._save_picks()

    def select_preset(self, index: int) -> None:
        if self.poll().can_pick_preset and 0 <= index < len(self._presets):
            self._preset = self._presets[index]
            self._save_picks()

    def _save_picks(self) -> None:
        choice: dict[str, str | int | None] = {"preset": self._preset.path.name if self._preset else None,
                                              "class": None}
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
        request = self._submit(commands.Start(self._preset.fixed or self._character, self._preset.path))
        if request is not None:
            self._last_start = request
            self._pending_start = True
        return request

    def control(self, action: commands.Control, *, session_id: str) -> Path | None:
        view = self.poll()
        if (not view.can_control or view.session_id != session_id
                or (action in ("pause", "resume") and not view.can_pause)
                or (action == "pause" and view.paused) or (action == "resume" and not view.paused)):
            return None
        return self._submit(action)

    def patch_command(self, command: commands.PatchCommand) -> Path | None:
        if self.poll().updates.action_blocker:
            return None
        request = self._submit(command)
        if request is not None:
            self._patch_request = command, request
        return request

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
