"""Display-independent view of the AFK service's file interface."""

import json
import math
import subprocess
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import assets
from ..core import app_update, catalog, commands, game_update
from ..core.history import read_history
from ..core.profile import ProfileNotFound, find_profile
from ..core.state import ServiceState, StateKind, read_state
from ..core.supervisor import session_log_dir
from ..platform import Platform


@dataclass(frozen=True)
class _Preset:
    path: Path
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
    targets = _object(os_, assets.targets_path())
    characters: dict[commands.Character, str] = {}
    for value in _mapping(targets.get("characters")).values():
        row = _mapping(value)
        character = _character(row.get("class"), row.get("job_path"))
        if character and isinstance(label := row.get("label"), str):
            characters[character] = label
    stages = {key: value for key, value in _mapping(targets.get("stages")).items() if isinstance(value, str)}
    presets = []
    for path in sorted(assets.presets_dir().glob("*.json")):
        if not (data := _object(os_, path)):
            continue
        objective = _label(data.get("objective", "balanced"))
        limits = [label.format(value) for key, label in (
            ("run_minutes", "{:g} min per run"), ("max_runs", "{:g} runs"),
            ("max_minutes", "{:g} min per session"), ("stop_after_wins", "{:g} wins"),
        ) if (value := _number(data.get(key))) is not None and value > 0]
        description = " · ".join((f"Objective: {objective}",
                                  f"Automatic difficulty ceiling: {data.get('danger_ceiling', 30)}",
                                  ", ".join(limits) if limits else "No run limits"))
        presets.append(_Preset(path, description))
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


def _catalog_refresh(latest: dict[str, Any] | None) -> str:
    if latest is not None:
        try:
            return datetime.fromtimestamp(latest["written_at"]).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError, OverflowError):
            pass
    return ""


def _locations(latest: dict[str, Any] | None) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = [{"id": None, "label": "Automatic", "enabled": True}]
    for item in latest["locations"] if latest is not None else ():
        row = _mapping(item)
        sid, name = _text(row.get("id")), _text(row.get("name"))
        lo, hi = row.get("min_difficulty"), row.get("max_difficulty")
        if sid and name and type(lo) is int and type(hi) is int and 1 <= lo <= hi <= 30:
            options.append({"id": sid, "label": name, "enabled": row.get("unlocked") is True,
                            "min_difficulty": lo, "max_difficulty": hi})
    if latest is not None:
        unlocked = [row for row in options[1:] if row["enabled"]]
        options.append({"id": {"mode": "rotation"}, "label": "All locations in turn", "enabled": True,
                        "min_difficulty": max((row["min_difficulty"] for row in unlocked), default=1),
                        "max_difficulty": min((row["max_difficulty"] for row in unlocked), default=0)})
    return options


def _difficulties(location: dict[str, Any]) -> list[str]:
    if location["id"] is None:
        return ["Automatic"]
    return ["Automatic", *(str(level) for level in range(location["min_difficulty"], location["max_difficulty"] + 1))]


def _oath_rows(latest: dict[str, Any] | None, selected: dict[str, int]) -> list[dict[str, Any]]:
    catalog_rows = latest["oaths"] if latest is not None else []
    rows = {}
    for item in catalog_rows:
        oath = _mapping(item)
        oath_id, name = _text(oath.get("id")), _text(oath.get("name"))
        ranks = []
        for value in oath.get("ranks", []) if isinstance(oath.get("ranks"), list) else ():
            rank = _mapping(value)
            if type(rank.get("rank")) is int and rank["rank"] > 0 and type(rank.get("points")) is int:
                ranks.append(rank)
        if oath_id and name and ranks:
            rows[oath_id] = (name, ranks)
    # A remembered choice removed by a catalog refresh must be visible and removable.
    if latest is not None:
        for oath_id in selected:
            rows.setdefault(oath_id, (oath_id, []))
    result = []
    for oath_id, (name, ranks) in rows.items():
        options = [{"rank": 0, "points": 0, "description": ""}, *ranks]
        index = next((i for i, option in enumerate(options) if option["rank"] == selected.get(oath_id, 0)), -1)
        result.append({"id": oath_id, "label": name, "ranks": options, "selected_index": index})
    return result


def _legendary_names(latest: dict[str, Any] | None) -> dict[str, str]:
    names = {}
    for item in latest["legendaries"] if latest is not None else ():
        row = _mapping(item)
        item_id, name = _text(row.get("id")), _text(row.get("name"))
        if item_id.strip() and "\0" not in item_id and name:
            names[item_id] = name
    return names


def _wishlist_rows(names: dict[str, str], owned_ids: list, wishlist: list[str]) -> list[dict[str, Any]]:
    selected = set(wishlist)
    owned = {item for item in owned_ids if isinstance(item, str)}
    # A saved item missing from the latest catalog must still be removable.
    return [{"id": item, "label": name, "owned": item in owned, "selected": item in selected}
            for item, name in sorted(({item: item for item in wishlist} | names).items(),
                                     key=lambda pair: (pair[1].casefold(), pair[0]))]


def _keep_text(run: dict[str, Any], item_names: dict[str, str]) -> list[str]:
    parts = []
    if isinstance(items := run.get("kept"), list):
        kept = [item_names.get(item, _label(item)) for item in items if isinstance(item, str) and item]
        if kept:
            parts.append(f"Kept: {', '.join(kept)}")
    if isinstance(items := run.get("keep_skipped"), list):
        skipped = []
        for item in items:
            row = _mapping(item)
            if item_id := _text(row.get("id")):
                name = item_names.get(item_id, _label(item_id))
                reason = _text(row.get("reason")).replace("_", " ")
                skipped.append(f"{name} ({reason})" if reason else name)
        if skipped:
            parts.append(f"Wishlist skipped: {', '.join(skipped)}")
    return parts


def _target_text(stage: object, danger: object, names: dict[str, str], oath_points: object) -> str:
    parts = [names.get(stage, stage)] if isinstance(stage, str) and stage else []
    if level := _number(danger):
        parts.append(f"Difficulty {level:.0f}")
    if (points := _number(oath_points)) is not None:
        parts.append(f"Oath points: {points:.0f}")
    return " · ".join(parts)


@dataclass(frozen=True)
class HistoryRow:
    date: str
    title: str
    summary: str
    session_id: str = ""
    run_choices: list[str] = field(default_factory=list)


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
    check_again_feedback: str = ""
    app_check: str = "No update check yet."
    previous_app_version: str = ""
    can_rollback: bool = False
    rollback_feedback: str = ""


@dataclass(frozen=True)
class QuarantineView:
    reason: str = ""
    detail: str = ""
    action: str = ""
    needs_check_again: bool = False
    can_check_again: bool = False
    attempts: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


def _history_view(rows: list[dict[str, Any]], names: dict[str, str], item_names: dict[str, str]) -> HistoryView:
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
                if isinstance(failures := row.get("attempt_failures"), list):
                    for failure in failures:
                        if (label := _label(failure)) and label not in summary:
                            summary.append(label)
                choices = []
                if isinstance(runs := row.get("run_choices"), list):
                    for value in runs:
                        run = _mapping(value)
                        target = _target_text(run.get("stage"), run.get("danger"), names, run.get("oath_points"))
                        if target:
                            number = _text(run.get("run_id")).rpartition("-r")[2]
                            prefix = f"Run {number} · {target}" if number.isdecimal() else target
                            choices.append(" · ".join([prefix, *_keep_text(run, item_names)]))
                entries.append(HistoryRow(date, f"AFK session · {_label(row.get('outcome')) or _DASH}",
                                          " · ".join(summary), session, choices))
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
    can_resume: bool = False
    can_control: bool = False
    characters: list[str] = field(default_factory=list)
    presets: list[str] = field(default_factory=list)
    character_index: int = -1
    preset_index: int = -1
    locations: list[dict[str, Any]] = field(default_factory=list)
    location_index: int = 0
    difficulties: list[str] = field(default_factory=list)
    difficulty_index: int = 0
    can_pick_run_choice: bool = False
    oaths: list[dict[str, Any]] = field(default_factory=list)
    oath_points: int = 0
    can_pick_oaths: bool = False
    wishlist_items: list[dict[str, Any]] = field(default_factory=list)
    wishlist_count: int = 0
    can_edit_wishlist: bool = False
    maintenance: dict[str, bool] = field(default_factory=lambda: commands.SessionSettings().maintenance())
    can_edit_maintenance: bool = False
    can_start: bool = False
    can_pick_character: bool = False
    can_pick_preset: bool = False
    preset_description: str = ""
    catalog_refresh: str = ""
    start_reason: str = ""
    start_refusal: str = ""
    resume_refusal: str = ""
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
        if self._character not in self._characters:
            self._character = next(iter(self._characters), None)
        self._preset = next((p for p in self._presets if p.path.name == saved.get("preset")), None)
        if self._preset is None:
            self._preset = next((p for p in self._presets if p.path.name == "night.json"),
                                self._presets[0] if self._presets else None)
        try:
            self._session_settings = commands.SessionSettings.decode(saved["settings"])
        except (KeyError, ValueError):
            self._session_settings = commands.SessionSettings()
        self._last_start: Path | None = None
        self._pending_start = False
        self._last_resume: tuple[Path, str] | None = None
        self._action_error = ""
        self._patch_request: tuple[commands.PatchCommand, Path] | None = None
        self._app_version = assets.version()
        self._rollback_request: Path | None = None
        self._history_rows: list[dict[str, Any]] = []
        self._history = HistoryView()
        self._history_stage_names: dict[str, str] = {}
        self._history_item_names: dict[str, str] = {}
        self._last_update: tuple[str, str] = ("No outcome yet", "")

    def poll(self) -> SessionView:
        state = read_state(self._os)
        paused = state.farmer_phase == "paused"
        latest = catalog.read_latest(self._os)
        locations = _locations(latest)
        names = self._stages | {row["id"]: row["label"] for row in locations if isinstance(row["id"], str)}
        item_names = _legendary_names(latest)
        self._refresh_history(names, item_names)
        location = self._session_settings.location
        level = self._session_settings.difficulty
        location_index = next((i for i, row in enumerate(locations) if row["enabled"] and row["id"] == location),
                              -1 if paused else 0)
        difficulties = _difficulties(locations[max(0, location_index)])
        difficulty_index = (difficulties.index(str(level)) if str(level) in difficulties
                            else (-1 if paused and level is not None else 0))
        oath_difficulty = level == 30 and difficulty_index > 0
        oaths = _oath_rows(latest, self._session_settings.oaths)
        unavailable_oaths = [oath for oath in oaths if oath["selected_index"] < 0]
        oath_blocker = ""
        if unavailable_oaths:
            names_unavailable = ", ".join(oath["label"] for oath in unavailable_oaths)
            oath_blocker = f"Saved oaths unavailable: {names_unavailable}. Choose Show oaths and set them to Off."
        if unavailable_oaths and not oath_difficulty:
            # Outside fixed difficulty 30, allow only clearing unavailable ranks.
            oaths = [oath | {"ranks": oath["ranks"][:1]} for oath in unavailable_oaths]
        oath_points = sum(oath["ranks"][i]["points"] for oath in oaths
                          if (i := oath["selected_index"]) >= 0) if oath_difficulty else 0
        status = self._read_status(state)
        preset = self._preset
        options = list(self._characters)
        characters = list(self._characters.values())
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
        reason = self._start_blocker(state, busy, quarantine)
        refusal = self._start_refusal(state)
        if self._pending_start and not reason:
            reason = "Start requested; waiting for the service."
        rates = _mapping(status.get("rates"))
        materials = f"{_format_number(rates.get('ore_h'), 1)} / {_format_number(rates.get('crumbs_h'), 1)}"
        totals = _mapping(status.get("totals"))
        run, detail = self._run_text(status, totals, names)
        can_control = (state.kind is StateKind.ACTIVE and bool(state.session_id)
                       and farmer_phase in ("", "idle", "run", "settle", "keep", "maint", "paused")
                       and status.get("terminal") is not True)
        resume_refusal, resume_pending = self._resume_feedback(state, paused)
        can_resume = paused and can_control and not resume_pending
        can_pick_run_choice = (not busy and not self._pending_start) or can_resume
        wishlist = self._session_settings.wishlist
        return SessionView(
            phase=phase, heartbeat_age=_heartbeat_age(state.last_heartbeat),
            zeny=_format_number(rates.get("zeny_h")), materials=materials if rates else _DASH,
            kills=_format_number(rates.get("kills_min"), 1), current_run=run, run_detail=detail,
            run_totals=" · ".join(f"{_format_number(totals.get(key))} {label}"
                                  for key, label in (("runs", "settled"), ("wins", "wins"), ("lost", "lost")))
            if totals else _DASH,
            session_id=state.session_id or "", active=busy, paused=paused,
            can_control=can_control, can_pause=can_control and bool(farmer_phase),
            can_resume=can_resume and not oath_blocker,
            characters=characters, presets=presets,
            character_index=options.index(self._character) if self._character in self._characters else -1,
            preset_index=self._presets.index(preset) if preset else -1,
            can_start=not (reason or oath_blocker), can_pick_character=not busy and bool(characters),
            can_pick_preset=not busy and bool(presets), preset_description=preset.description if preset else "",
            locations=locations, location_index=location_index, difficulties=difficulties,
            difficulty_index=difficulty_index, can_pick_run_choice=can_pick_run_choice,
            oaths=oaths, oath_points=oath_points,
            can_pick_oaths=bool(oaths and (oath_difficulty or oath_blocker) and (not reason or can_resume)),
            wishlist_items=_wishlist_rows(item_names, latest["owned_item_ids"], wishlist) if latest is not None else [],
            wishlist_count=len(wishlist), can_edit_wishlist=latest is not None and can_pick_run_choice,
            maintenance=self._session_settings.maintenance(), can_edit_maintenance=not reason or can_resume,
            catalog_refresh=_catalog_refresh(latest),
            start_reason=reason or oath_blocker, start_refusal=refusal,
            resume_refusal=(oath_blocker or resume_refusal) if can_resume else resume_refusal,
            action_error=self._action_error, service_missing=missing,
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

    def _run_text(self, status: dict[str, Any], totals: dict[str, Any], names: dict[str, str]) -> tuple[str, str]:
        if status.get("phase") not in ("run", "settle", "keep", "maint") or not status.get("run_id"):
            return _DASH, ""
        game = _mapping(status.get("game"))
        target = _mapping(status.get("target"))
        choice = _target_text(target.get("stage") or game.get("stage"), target.get("danger") or game.get("danger"),
                              names, target.get("oath_points"))
        started = _number(totals.get("started"))
        parts = [f"Run {started:.0f}" if started else "Run in progress"]
        if choice:
            parts.append(choice)
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

    def _refresh_history(self, names: dict[str, str], item_names: dict[str, str]) -> None:
        try:
            rows = read_history(self._os)
        except OSError:
            return  # Retain the last readable history until the file becomes available.
        if (rows != self._history_rows or names != self._history_stage_names
                or item_names != self._history_item_names):
            self._history_rows = rows
            self._history_stage_names = names
            self._history_item_names = item_names
            self._history = _history_view(rows, names, item_names)
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
        check_again_feedback = ""
        restore_requested_here = False
        restore = state.last_restore or {}
        if self._patch_request:
            command, request = self._patch_request
            restore_requested_here = command == "restore_official" and restore.get("request") == request.name
            for row in state.command_refusals:
                if row.get("request") == request.name and row.get("command") == command:
                    action = "Restore" if command == "restore_official" else "Check again"
                    feedback = f"{action} refused: {_text(row.get('reason'))}"
                    if command == "check_again":
                        check_again_feedback = feedback
                    break
        if not feedback and not busy and state.kind is not StateKind.STALE:
            outcome = restore.get("outcome")
            if ((outcome == "restored" and state.keep_official)
                    or (outcome == "restore_failed" and restore_requested_here)):
                feedback = _text(restore.get("reason"))
        app = app_update.read_update_status(self._os)
        check = "No update check yet."
        if app.reason:
            if app.last_checked is None:
                check = f"No successful update check yet ({app.reason})."
            else:
                days = max(0, int((time.time() - app.last_checked) // 86400))
                check = f"Updates not checked for {days} {'day' if days == 1 else 'days'} ({app.reason})."
        elif app.last_checked is not None:
            when = datetime.fromtimestamp(app.last_checked).strftime("%Y-%m-%d %H:%M")
            check = f"Last checked: {when}."
        if app.switch_overdue:
            check = "App update did not finish. Restart the service; if it cannot start, rerun the previous setup."
        elif app.switching:
            check = "App update is waiting for the service to restart."
        elif app.staged and app.staged != app.version and not app.reason:
            check = f"Version {app.staged} downloaded; it will install after the AFK session and game close."
        rollback_feedback = ""
        if self._rollback_request is not None:
            name = self._rollback_request.name
            if refusal := next((row for row in state.command_refusals if row.get("request") == name), None):
                rollback_feedback = f"Rollback refused: {_text(refusal.get('reason'))}"
            elif self._rollback_request.exists():
                rollback_feedback = "Rollback queued; it will run when the game is closed."
        return UpdatesView(title, detail, activity, activity_detail, *self._last_update, blocker, feedback,
                           app.version or self._app_version, check_again_feedback, check, app.previous or "",
                           bool(app.previous and not blocker and not app.switching
                                and not (self._rollback_request and self._rollback_request.exists())),
                           rollback_feedback)

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

    def _resume_feedback(self, state: ServiceState, paused: bool) -> tuple[str, bool]:
        if self._last_resume is None:
            return "", False
        request, session = self._last_resume
        if not paused or state.session_id != session:
            self._last_resume = None
            return "", False
        for row in state.command_refusals:
            if row.get("request") == request.name and row.get("command") == "resume":
                return _text(row.get("reason")), False
        return "", request.exists()

    def _start_blocker(self, state: ServiceState, busy: bool, quarantine: QuarantineView) -> str:
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
        if self._character is None:
            return "No character available."
        return ""

    def select_character(self, index: int) -> None:
        if self.poll().can_pick_character and 0 <= index < len(self._characters):
            self._character = list(self._characters)[index]
            self._save_picks()

    def select_preset(self, index: int) -> None:
        if self.poll().can_pick_preset and 0 <= index < len(self._presets):
            self._preset = self._presets[index]
            self._save_picks()

    def select_location(self, location: commands.LocationChoice) -> None:
        view = self.poll()
        selected = next((row for row in view.locations if row["id"] == location and row["enabled"]), None)
        if view.can_pick_run_choice and selected is not None:
            previous = str(self._session_settings.difficulty)
            difficulty = int(previous) if previous in _difficulties(selected) else None
            self._session_settings = replace(self._session_settings, location=location, difficulty=difficulty)
            self._save_picks()

    def select_difficulty(self, level: str) -> None:
        view = self.poll()
        if view.can_pick_run_choice and level in view.difficulties:
            self._session_settings = replace(self._session_settings, difficulty=None if level == "Automatic" else int(level))
            self._save_picks()

    def select_oath(self, oath_id: str, rank: int) -> None:
        view = self.poll()
        if not view.can_pick_oaths:
            return
        for oath in view.oaths:
            if oath["id"] == oath_id and any(option["rank"] == rank for option in oath["ranks"]):
                selected = self._session_settings.oaths.copy()
                if rank:
                    selected[oath_id] = rank
                else:
                    selected.pop(oath_id, None)
                self._session_settings = replace(self._session_settings, oaths=selected)
                self._save_picks()
                return

    def set_wishlisted(self, item_id: str, selected: bool) -> None:
        view = self.poll()
        if not view.can_edit_wishlist:
            return
        for row in view.wishlist_items:
            if row["id"] == item_id and row["selected"] != selected:
                wishlist = self._session_settings.wishlist
                self._session_settings = replace(self._session_settings, wishlist=(
                    [*wishlist, item_id] if selected else [item for item in wishlist if item != item_id]
                ))
                self._save_picks()
                return

    def set_maintenance(self, name: str, enabled: bool) -> None:
        if name in commands.MAINTENANCE_CONFIG_KEYS and self.poll().can_edit_maintenance:
            changes: dict[str, Any] = {name: enabled}
            self._session_settings = replace(self._session_settings, **changes)
            self._save_picks()

    def _selected_settings(self, view: SessionView, *, resuming: bool = False) -> commands.SessionSettings:
        settings = self._session_settings
        if not resuming:
            level = int(view.difficulties[view.difficulty_index]) if view.difficulty_index else None
            settings = replace(settings, location=view.locations[view.location_index]["id"], difficulty=level)
        return settings if settings.difficulty == 30 else replace(settings, oaths={})

    def _save_picks(self) -> None:
        choice: dict[str, Any] = {"preset": self._preset.path.name if self._preset else None, "class": None,
                                  "settings": asdict(self._session_settings)}
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
        view = self.poll()
        if not view.can_start or self._preset is None:
            return None
        request = self._submit(commands.Start(self._character, self._preset.path, self._selected_settings(view)))
        if request is not None:
            self._last_start = request
            self._patch_request = None
            self._pending_start = True
        return request

    def control(self, action: commands.Control, *, session_id: str) -> Path | None:
        view = self.poll()
        if (not view.can_control or view.session_id != session_id
                or (action in ("pause", "resume") and not view.can_pause)
                or (action == "pause" and view.paused) or (action == "resume" and not view.can_resume)):
            return None
        if action == "resume":
            # A stale catalog must not alter the remembered run choice; the farmer checks it live.
            request = self._submit(commands.Resume(self._selected_settings(view, resuming=True)))
            if request is not None:
                self._last_resume = request, session_id
            return request
        return self._submit(action)

    def patch_command(self, command: commands.PatchCommand) -> Path | None:
        if self.poll().updates.action_blocker:
            return None
        request = self._submit(command)
        if request is not None:
            self._patch_request = command, request
        return request

    def rollback_app(self) -> Path | None:
        if not self.poll().updates.can_rollback:
            return None
        self._rollback_request = self._submit("rollback_app")
        return self._rollback_request

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
