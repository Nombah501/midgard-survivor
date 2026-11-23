"""Display-independent view of the AFK service's file interface."""

import json
import math
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

from .. import assets
from ..core import _app_releases, app_update, catalog, commands, doctor, game_update
from ..core.history import journal_run_counts, night_summary, read_history, read_run_journal, run_outcome, session_timing
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
        if data.get("endless") is True and data.get("endless_minutes") == data.get("endless_mvps") == 0:
            description += " · Endless until the final boss"
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
_RUN_PHASES = ("run", "settle", "keep", "maint")
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
    ("wins", "Wins"),
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


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return _DASH
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min" if minutes else f"{secs} s"


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


def _locations(latest: dict[str, Any] | None, tower: catalog.TowerCatalog | None,
               choice: commands.LocationTower | None, *, paused: bool) -> list[dict[str, Any]]:
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
    variants: tuple[tuple[commands.TowerKind, str], ...] = (("normal", "Endless Tower"), ("hel", "Torre de Hel"))
    for kind, label in variants:
        floor = choice["floor"] if choice and choice["kind"] == kind else (
            tower.checkpoints[0] if kind == "normal" and tower and tower.checkpoints else 1
        )
        reason = "Finish this session and Start to change a Tower choice." if paused else catalog.tower_blocker(tower, kind)
        options.append({"id": {"mode": "tower", "kind": kind, "floor": floor}, "label": label,
                        "enabled": not reason, "reason": reason})
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


def _tower_run_label(stage: object, floor: object) -> str:
    if stage not in ("tower", "hel"):
        return ""
    label = "Tower" if stage == "tower" else "Hel"
    return f"{label} F{floor}" if type(floor) is int and floor >= 0 else label


def _run_number(run_id: object) -> str:
    _, separator, number = _text(run_id).rpartition("-r")
    return number if separator and number.isascii() and number.isdecimal() else ""


def _run_segment(stage: object, outcome: str, names: dict[str, str], number: str) -> dict[str, str]:
    key = _text(stage)
    label = names.get(key, "").strip() or _label(key).strip() or "Unknown location"
    words = label.split()
    short = words[0] + (" " + "".join(word[0] + "." for word in words[1:]) if len(words) > 1 else "")
    return {"label": label, "short": short, "outcome": outcome, "number": number}


def _settled_band(rows: list[dict[str, Any]], names: dict[str, str]) -> list[dict[str, str]]:
    band = []
    for row in rows:
        stage = row.get("stage")
        number = _run_number(row.get("run_id"))
        outcome = run_outcome(row)
        if label := _tower_run_label(stage, row.get("tower_floor_best")):
            band.append({"label": label, "short": label, "outcome": outcome, "number": number})
        else:
            band.append(_run_segment(stage, outcome, names, number))
    return band


def _session_measurements(rows: list[dict[str, Any]], band: list[dict[str, str]],
                          totals: dict[str, Any]) -> tuple[dict[str, int | float], dict[str, int | float]]:
    numbers: dict[str, int | float] = {}
    metrics: dict[str, int | float] = {}
    materials: dict[str, int | float] = {}
    for row in rows:
        for key, target, label in (("zeny_gain", numbers, "zeny"), ("kills", metrics, "Kills"),
                                   ("cards_gain", metrics, "Cards")):
            if (value := _number(row.get(key))) is not None:
                target[label] = target.get(label, 0) + value
        for key, raw in _mapping(row.get("materials")).items():
            if (value := _number(raw)) is not None:
                materials[key] = materials.get(key, 0) + value
    if (_number(totals.get("runs")) or 0) >= len(rows):
        if (zeny := _number(totals.get("zeny"))) is not None:
            numbers["zeny"] = zeny
        if (kills := _number(totals.get("kills"))) is not None:
            metrics["Kills"] = kills
        materials.update({key: value for key, raw in _mapping(totals.get("materials")).items()
                          if (value := _number(raw)) is not None})
    runs = _number(totals.get("runs"))
    if counts := journal_run_counts(totals, Counter(mark["outcome"] for mark in band)):
        numbers.update(counts)
    elif runs is not None:
        numbers["runs"] = runs
        if (wins := _number(totals.get("wins"))) is not None:
            numbers["wins"] = wins
            losses = _number(totals.get("losses"))
            numbers["losses"] = max(0, runs - wins) if losses is None else losses

    cards = metrics.pop("Cards", None)
    metrics.update({key.replace("_", " ").title(): materials[key] for key in sorted(materials) if materials[key]})
    if cards is not None:
        metrics["Cards"] = cards
    return numbers, metrics


@dataclass(frozen=True)
class HistoryRow:
    date: str
    title: str
    summary: str
    session_id: str = ""
    run_choices: list[str] = field(default_factory=list)
    session_runs: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class HistoryMetric:
    label: str
    value: str


@dataclass(frozen=True)
class NightView:
    window: str = ""
    totals: list[HistoryMetric] = field(default_factory=list)


@dataclass(frozen=True)
class HistoryView:
    rows: list[HistoryRow] = field(default_factory=list)
    latest_session_id: str = ""
    latest_session_date: str = ""
    latest_session_zeny: str = ""
    session_facts: list[HistoryMetric] = field(default_factory=list)
    stop_reason: str = ""
    failure_reasons: str = ""
    totals: list[HistoryMetric] = field(default_factory=list)
    rewards: str = ""
    materials: str = ""
    night: NightView = field(default_factory=NightView)


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
    latest_app_version: str = _DASH
    check_again_feedback: str = ""
    app_check: str = "Not checked yet"
    app_check_reason: str = ""
    app_last_checked: str = "Never"
    app_update_detail: str = ""
    can_check_app: bool = False
    app_changelog: str = ""
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


@dataclass(frozen=True)
class DiagnosticsView:
    checks: list[doctor.Check] = field(default_factory=list)
    check_error: str = ""
    repair_feedback: str = ""
    repair_blocker: str = ""
    can_repair: bool = False


def _night_view(rows: list[dict[str, Any]], today: date, active: dict[str, Any] | None = None) -> NightView:
    summary = night_summary(rows, today, active)
    window = f"{today - timedelta(days=1):%d %b} 18:00 – {today:%d %b} 12:00 local"
    if not summary.sessions:
        return NightView(window)
    downtime = _format_duration(summary.downtime_s)
    if summary.partial_downtime and summary.downtime_s is not None:
        downtime = f"≥ {downtime}"
    return NightView(window, [
        HistoryMetric("Zeny", _format_number(summary.zeny)),
        HistoryMetric("Wins / runs", f"{_format_number(summary.wins)} / {_format_number(summary.runs)}"),
        HistoryMetric("Downtime", downtime),
    ])


def _history_report_rows(rows: list[dict[str, Any]], journal: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    reported = []
    for row in rows:
        runs = journal.get(_text(row.get("session_id"))) if row["kind"] == "session" else None
        if runs:
            totals = _mapping(row.get("totals"))
            # Older sessions persisted the farmer's victory counters. Prefer the journal without rewriting history.
            if counts := journal_run_counts(totals, Counter(map(run_outcome, runs))):
                row = row | {"totals": totals | counts}
        reported.append(row)
    return reported


def _history_view(rows: list[dict[str, Any]], names: dict[str, str], item_names: dict[str, str],
                  journal: dict[str, list[dict[str, Any]]], today: date) -> HistoryView:
    entries: list[HistoryRow] = []
    latest: dict[str, Any] | None = None
    latest_date = ""
    for row in sorted(rows, key=lambda row: row["timestamp"], reverse=True):
        try:
            date = datetime.fromtimestamp(row["timestamp"]).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError, OverflowError):
            continue
        match row["kind"]:
            case "session":
                session = _text(row.get("session_id"))
                quantities = _mapping(row.get("totals"))
                if session and latest is None:
                    latest, latest_date = row, date
                summary = [f"{_format_number(quantities[key])} {label}"
                           for key, label in (("runs", "runs"), ("wins", "wins"), ("zeny", "zeny"), ("losses", "losses"))
                           if _number(quantities.get(key)) is not None]
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
                            number = _run_number(run.get("run_id"))
                            prefix = f"Run {number} · {target}" if number else target
                            choices.append(" · ".join([prefix, *_keep_text(run, item_names)]))
                entries.append(HistoryRow(date, f"AFK session · {_label(row.get('outcome')) or _DASH}",
                                          " · ".join(summary), session, choices,
                                          _settled_band(journal.get(session, []), names)))
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

    night = _night_view(rows, today)
    if latest is None:
        return HistoryView(rows=entries, night=night)
    totals = _mapping(latest.get("totals"))
    timing = session_timing(latest)
    facts = [
        HistoryMetric("Elapsed", _format_duration(timing.elapsed_s)),
        HistoryMetric("Time in runs", _format_duration(timing.run_s)),
        HistoryMetric("Downtime", _format_duration(timing.downtime_s)),
        HistoryMetric("Runs started", _format_number(totals.get("started"))),
        HistoryMetric("Settled", _format_number(totals.get("runs"))),
        HistoryMetric("Lost runs", _format_number(totals.get("lost"))),
        HistoryMetric("Restarts", _format_number(latest.get("restarts"))),
        HistoryMetric("Attempt failures", _format_number(latest.get("attempt_failure_count"))),
    ]
    hours = timing.elapsed_s / 3600 if timing.elapsed_s is not None else None
    rewards = " · ".join(f"{_format_number(value / hours)} {label}"
                         for key, label in (("zeny", "zeny"), ("xp", "XP"), ("coins", "coins"),
                                            ("ymir", "Ymir"), ("cards_gain", "cards"))
                         if hours and hours > 0 and (value := _number(totals.get(key))) is not None) or _DASH
    materials = [(key, count) for key, value in _mapping(totals.get("materials")).items()
                 if (count := _number(value)) is not None and count != 0]
    failures = latest.get("attempt_failures")
    return HistoryView(
        rows=entries, latest_session_id=_text(latest.get("session_id")), latest_session_date=latest_date,
        latest_session_zeny=_format_number(totals["zeny"]) if _number(totals.get("zeny")) is not None else "",
        session_facts=facts, stop_reason=_label(latest.get("reason")) or _DASH,
        failure_reasons=" · ".join(label for failure in failures if (label := _label(failure)))
        if isinstance(failures, list) else "",
        totals=[HistoryMetric(label, _format_number(totals.get(key))) for key, label in _TOTALS],
        rewards=rewards, materials=" · ".join(f"{key.replace('_', ' ').title()} {_format_number(count)}"
                                              for key, count in sorted(materials, key=lambda entry: (-entry[1], entry[0])))
        or _DASH, night=night,
    )


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
    session_runs: list[dict[str, str]] = field(default_factory=list)
    session_numbers: dict[str, int | float] = field(default_factory=dict)
    session_metrics: dict[str, int | float] = field(default_factory=dict)
    session_duration: int = 0
    last_event: str = ""
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
    can_pick_location: bool = False
    tower_selected: bool = False
    tower_normal: bool = False
    tower_floors: list[str] = field(default_factory=list)
    tower_floor_index: int = -1
    tower_snapshot: str = ""
    difficulties: list[str] = field(default_factory=list)
    difficulty_index: int = 0
    can_pick_run_choice: bool = False
    oaths: list[dict[str, Any]] = field(default_factory=list)
    oath_points: int = 0
    can_pick_oaths: bool = False
    wishlist_items: list[dict[str, Any]] = field(default_factory=list)
    wishlist_count: int = 0
    can_edit_wishlist: bool = False
    keep_unowned_legendaries: bool = False
    experimental_speed: bool = False
    maintenance: dict[str, bool] = field(default_factory=lambda: commands.SessionSettings().maintenance())
    can_edit_maintenance: bool = False
    show_game_window: bool = False
    can_change_show_game_window: bool = False
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
    diagnostics: DiagnosticsView = field(default_factory=DiagnosticsView)


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
        try:
            self._app_channel_configured = bool(_app_releases.MINISIGN_PUBLIC_KEY and _app_releases.update_base_url())
        except (_app_releases.ReleaseError, ValueError):
            self._app_channel_configured = False
        self._app_check_feedback = ""
        self._rollback_request: Path | None = None
        self._history_rows: list[dict[str, Any]] = []
        self._history_reports: list[dict[str, Any]] = []
        self._history = HistoryView()
        self._history_date: date | None = None
        self._history_stage_names: dict[str, str] = {}
        self._history_item_names: dict[str, str] = {}
        self._history_journal: dict[str, list[dict[str, Any]]] = {}
        self._journal: dict[str, list[dict[str, Any]]] = {}
        self._journal_version: tuple[Path, int, int] | None = None
        self._last_journal_session = ""
        self._last_update: tuple[str, str] = ("No outcome yet", "")
        self._checks: list[doctor.Check] = []
        self._check_error = ""
        self._repair_request: Path | None = None
        self._repair_feedback = ""
        self._repair_succeeded = False

    def poll(self) -> SessionView:
        state = read_state(self._os)
        paused = state.farmer_phase == "paused"
        missing = state.kind is StateKind.STALE
        busy = not missing and (state.session_id is not None or state.kind is StateKind.ACTIVE)
        saved = _object(self._os, self._os.app_data_dir() / "session.json") if busy and state.session_id else {}
        active_tower = None
        if state.session_id and saved.get("id") == state.session_id:
            try:
                active_tower = commands.SessionSettings.decode(_mapping(saved.get("start")).get("settings")).tower
            except ValueError:
                pass
        latest = catalog.read_latest(self._os)
        tower = catalog.tower_catalog(latest)
        tower_choice = active_tower or self._session_settings.tower
        locations = _locations(latest, tower, tower_choice, paused=paused)
        names = self._stages | {row["id"]: row["label"] for row in locations if isinstance(row["id"], str)}
        item_names = _legendary_names(latest)
        try:
            profile = find_profile(self._os.godot_user_data_root())
        except (OSError, ProfileNotFound):
            profile = None
        self._refresh_journal(profile)
        now = time.time()
        today = datetime.fromtimestamp(now).date()
        self._refresh_history(names, item_names, today)
        location = tower_choice or self._session_settings.location
        level = self._session_settings.difficulty
        location_index = next((i for i, row in enumerate(locations)
                               if row["id"] == location and (row["enabled"] or tower_choice)),
                              -1 if paused else 0)
        difficulties = [] if tower_choice else _difficulties(locations[max(0, location_index)])
        difficulty_index = (difficulties.index(str(level)) if str(level) in difficulties
                            else (-1 if paused and level is not None else 0))
        oath_difficulty = level == 30 and difficulty_index > 0
        oaths = [] if tower_choice else _oath_rows(latest, self._session_settings.oaths)
        tower_blocker = ""
        tower_floors: list[str] = []
        tower_floor_index = -1
        snapshot_text = ""
        if tower_choice is not None:
            kind, floor = tower_choice["kind"], tower_choice["floor"]
            if kind == "normal" and tower is not None:
                tower_floors = [str(checkpoint) for checkpoint in tower.checkpoints]
                if str(floor) in tower_floors:
                    tower_floor_index = tower_floors.index(str(floor))
            if not active_tower:
                tower_blocker = locations[location_index]["reason"] or catalog.tower_blocker(tower, kind, floor)
            if not busy and tower and not locations[location_index]["reason"] and (snapshot := tower.best_snapshot):
                saved_on = datetime.fromtimestamp(snapshot.saved_at).strftime("%Y-%m-%d")
                snapshot_text = f"{snapshot.job} ({_label(snapshot.class_id)}) · Level {snapshot.level} · {saved_on}"
        unavailable_oaths = [oath for oath in oaths if oath["selected_index"] < 0]
        oath_blocker = ""
        if unavailable_oaths:
            names_unavailable = ", ".join(oath["label"] for oath in unavailable_oaths)
            oath_blocker = f"Saved oaths unavailable: {names_unavailable}. Open Oaths and set them to Off."
        if unavailable_oaths and not oath_difficulty:
            # Outside fixed difficulty 30, allow only clearing unavailable ranks.
            oaths = [oath | {"ranks": oath["ranks"][:1]} for oath in unavailable_oaths]
        oath_points = sum(oath["ranks"][i]["points"] for oath in oaths
                          if (i := oath["selected_index"]) >= 0) if oath_difficulty else 0
        status = self._read_status(state, profile)
        preset = self._preset
        options = list(self._characters)
        characters = list(self._characters.values())
        presets = [p.path.name for p in self._presets]
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
        run_id = _text(status.get("run_id"))
        started = _number(totals.get("started"))
        current_number = _run_number(run_id) or (f"{started:.0f}" if started else "")
        run, detail = self._run_text(status, current_number, names)
        history = self._history
        journal_id = (state.session_id or "") if busy else (history.latest_session_id or self._last_journal_session)
        journal = self._journal.get(journal_id, [])
        band = _settled_band(journal, names)
        numbers, metrics = _session_measurements(journal, band, totals)
        duration = 0
        started_at = _number(saved.get("started_at"))
        if busy and state.session_id and saved.get("id") == state.session_id and started_at is not None and started_at <= now:
            duration = int(now - started_at)
            active = {"session_id": state.session_id, "started_at": started_at, "timestamp": now,
                      "totals": {key: numbers.get(key, 0) for key in ("zeny", "wins", "runs")}}
            history = replace(history, night=_night_view(self._history_reports, today, active))
        if status.get("phase") in _RUN_PHASES and not (run_id and any(row.get("run_id") == run_id for row in journal)):
            stage = _mapping(status.get("target")).get("stage") or _mapping(status.get("game")).get("stage")
            band.append(_run_segment(stage, "current", names, current_number))
        last_event = ""
        if journal:
            last = journal[-1]
            notes = _keep_text(last, item_names)
            if notes:
                last_event = " · ".join(notes)
            else:
                mark = band[len(journal) - 1]
                outcome = {"win": "won", "loss": "lost", "aborted": "aborted"}[mark["outcome"]]
                if last.get("stage") in ("tower", "hel") and last.get("end_cause") == "finish":
                    outcome = "finished"
                last_event = f"{mark['label']} · Run {outcome}"
        can_control = (state.kind is StateKind.ACTIVE and bool(state.session_id)
                       and farmer_phase in ("", "idle", "run", "settle", "keep", "maint", "paused")
                       and status.get("terminal") is not True)
        resume_refusal, resume_pending = self._resume_feedback(state, paused)
        can_resume = paused and can_control and not resume_pending
        can_pick_run_choice = (not busy and not self._pending_start) or can_resume
        choice_blocker = tower_blocker or oath_blocker
        wishlist = self._session_settings.wishlist
        return SessionView(
            phase=phase, heartbeat_age=_heartbeat_age(state.last_heartbeat),
            zeny=_format_number(rates.get("zeny_h")), materials=materials if rates else _DASH,
            kills=_format_number(rates.get("kills_min"), 1), current_run=run, run_detail=detail,
            run_totals=" · ".join(f"{_format_number(value)} {label}" for value, label in
                                  ((numbers.get("runs"), "settled"), (numbers.get("wins"), "wins"),
                                   (totals.get("lost"), "lost"))) if numbers else _DASH,
            session_runs=band, session_numbers=numbers, session_metrics=metrics,
            session_duration=duration, last_event=last_event,
            session_id=state.session_id or "", active=busy, paused=paused,
            can_control=can_control, can_pause=can_control and bool(farmer_phase),
            can_resume=can_resume and not choice_blocker,
            characters=characters, presets=presets,
            character_index=options.index(self._character) if self._character in self._characters else -1,
            preset_index=self._presets.index(preset) if preset else -1,
            can_start=not (reason or choice_blocker),
            can_pick_character=not busy and not tower_choice and bool(characters),
            can_pick_preset=not busy and bool(presets), preset_description=preset.description if preset else "",
            locations=locations, location_index=location_index, difficulties=difficulties,
            difficulty_index=difficulty_index, can_pick_run_choice=can_pick_run_choice,
            can_pick_location=can_pick_run_choice and not active_tower,
            tower_selected=tower_choice is not None, tower_normal=bool(tower_choice and tower_choice["kind"] == "normal"),
            tower_floors=tower_floors, tower_floor_index=tower_floor_index, tower_snapshot=snapshot_text,
            oaths=oaths, oath_points=oath_points,
            can_pick_oaths=bool(oaths and (oath_difficulty or oath_blocker) and (not reason or can_resume)),
            wishlist_items=_wishlist_rows(item_names, latest["owned_item_ids"], wishlist) if latest is not None else [],
            wishlist_count=len(wishlist), can_edit_wishlist=latest is not None and can_pick_run_choice,
            keep_unowned_legendaries=self._session_settings.keep_unowned_legendaries,
            experimental_speed=self._session_settings.experimental_speed,
            maintenance=self._session_settings.maintenance(), can_edit_maintenance=not reason or can_resume,
            show_game_window=self._session_settings.show_game_window,
            can_change_show_game_window=not oath_blocker and (not reason or can_resume),
            catalog_refresh=_catalog_refresh(latest),
            start_reason=reason or choice_blocker, start_refusal=refusal,
            resume_refusal=(choice_blocker or resume_refusal) if can_resume else resume_refusal,
            action_error=self._action_error, service_missing=missing,
            history=history, updates=updates, quarantine=quarantine,
            diagnostics=self._diagnostics(state),
        )

    def _read_status(self, state: ServiceState, profile: Path | None) -> dict[str, Any]:
        if profile is None or state.kind is not StateKind.ACTIVE or not state.session_id or not state.farmer_phase:
            return {}
        status = _object(self._os, profile / "farmer_status.json")
        return status if status.get("session") == state.session_id else {}

    def _run_text(self, status: dict[str, Any], run_number: str, names: dict[str, str]) -> tuple[str, str]:
        if status.get("phase") not in _RUN_PHASES or not status.get("run_id"):
            return _DASH, ""
        game = _mapping(status.get("game"))
        target = _mapping(status.get("target"))
        choice = _target_text(target.get("stage") or game.get("stage"), target.get("danger") or game.get("danger"),
                              names, target.get("oath_points"))
        parts = [f"Run {run_number}" if run_number else "Run in progress"]
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

    def _refresh_journal(self, profile: Path | None) -> None:
        path = profile / "farmer_runs.jsonl" if profile is not None else None
        if path is not None:
            try:
                info = path.stat()
                version = path, info.st_mtime_ns, info.st_size
                if self._journal_version == version:
                    return
                rows: dict[str, list[dict[str, Any]]] = {}
                seen: set[tuple[str, str]] = set()
                latest = ""
                for row in read_run_journal(self._os, path):
                    session = _text(row.get("session"))
                    if not session:
                        continue
                    if run_id := _text(row.get("run_id")):
                        if (session, run_id) in seen:
                            continue
                        seen.add((session, run_id))
                    rows.setdefault(session, []).append(row)
                    latest = session
                self._journal_version, self._journal, self._last_journal_session = version, rows, latest
                return
            except FileNotFoundError:
                pass
            except OSError:
                if self._journal_version is not None and self._journal_version[0] == path:
                    return  # A temporarily unavailable file does not erase the last readable bands.
        if self._journal_version is not None:
            self._journal_version, self._journal, self._last_journal_session = None, {}, ""

    def _refresh_history(self, names: dict[str, str], item_names: dict[str, str], today: date) -> None:
        try:
            rows = read_history(self._os)
        except OSError:
            rows = self._history_rows  # Retain the last readable history.
        if (rows != self._history_rows or names != self._history_stage_names
                or item_names != self._history_item_names or self._journal is not self._history_journal
                or today != self._history_date):
            self._history_rows = rows
            self._history_stage_names = names
            self._history_item_names = item_names
            self._history_journal = self._journal
            self._history_reports = _history_report_rows(rows, self._journal)
            self._history = _history_view(self._history_reports, names, item_names, self._journal, today)
            self._history_date = today
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
        running = state.kind is not StateKind.STALE
        pending = running and app.check_pending
        version = app.version or self._app_version
        reason = ""
        if not self._app_channel_configured:
            check = "Channel not configured yet."
        elif pending:
            check = "Checking…"
        elif app.last_result == "error":
            check = "Failed"
            reason = app.reason or "No reason was reported."
        elif app.last_result == "up_to_date" or version == app.latest_version:
            check = "Up to date"
        elif app.last_result in ("staged", "excluded"):
            check = "Update available"
        else:
            check = "Not checked yet"
        when = (datetime.fromtimestamp(app.last_checked).strftime("%Y-%m-%d %H:%M")
                if app.last_result is not None and app.last_checked is not None else "Never")
        app_detail = self._app_check_feedback
        if app.switch_overdue:
            app_detail = "App update did not finish. Restart the service; if it cannot start, rerun the previous setup."
        elif app.switching:
            app_detail = "App update is waiting for the service to restart."
        elif not app_detail:
            if app.staged and app.staged != version and not app.reason:
                app_detail = f"Version {app.staged} downloaded; it will install after the AFK session and game close."
            elif app.last_result == "excluded" and app.latest_version != version:
                app_detail = "This version will not install automatically after rollback."
            elif self._app_channel_configured and not app.version:
                app_detail = "App updates need an installed release."
            elif self._app_channel_configured and not running:
                app_detail = "Start the service to check for App updates."
        changelog = app.changelog if app.latest_version and (
            app.last_result != "up_to_date" or version == app.latest_version
        ) else ""
        rollback_feedback = ""
        if self._rollback_request is not None:
            name = self._rollback_request.name
            if refusal := next((row for row in state.command_refusals if row.get("request") == name), None):
                rollback_feedback = f"Rollback refused: {_text(refusal.get('reason'))}"
            elif self._rollback_request.exists():
                rollback_feedback = "Rollback queued; it will run when the game is closed."
        return UpdatesView(
            title, detail, activity, activity_detail, *self._last_update, blocker, feedback,
            app_version=version, latest_app_version=app.latest_version or _DASH,
            check_again_feedback=check_again_feedback, app_check=check, app_check_reason=reason,
            app_last_checked=when,
            app_update_detail=app_detail,
            can_check_app=bool(app.version and self._app_channel_configured and running
                               and not pending and not app.switching),
            app_changelog=changelog,
            previous_app_version=app.previous or "",
            can_rollback=bool(app.previous and not blocker and not app.switching
                              and not (self._rollback_request and self._rollback_request.exists())),
            rollback_feedback=rollback_feedback,
        )

    def _farmer_patch_failed(self) -> bool:
        return any(row["id"] == "farmer_patch" and row["status"] == "fail" for row in self._checks)

    def _repair_blocker(self, state: ServiceState) -> str:
        if self._pending_start or state.session_id is not None or state.kind is StateKind.ACTIVE:
            return "Finish the AFK session before repairing."
        if state.kind is StateKind.STALE:
            return "Start the service before repairing."
        if state.kind in (StateKind.REBUILDING, StateKind.UPDATING):
            return "Wait for the current update to finish."
        try:
            try:
                (self._os.app_data_dir() / "session.json").stat()
            except FileNotFoundError:
                pass
            else:
                return "Finish the saved AFK session before repairing."
            if self._os.game_pids():
                return "Close the game before repairing."
        except (OSError, RuntimeError) as exc:
            return f"Could not check whether repair is safe: {exc}"
        return ""

    def _repair_status(self, state: ServiceState, request: Path) -> str:
        if request.exists():
            if state.kind is StateKind.STALE:
                return "Repair is queued; start the service to continue."
            if state.kind is StateKind.REBUILDING:
                return f"Repair in progress: {state.reason}."
            return "Repair queued; waiting for the service."

        # The service publishes the result before removing the request.
        state = read_state(self._os)
        for row in state.command_refusals:
            if row.get("request") == request.name and row.get("command") == "check_again":
                self._repair_request = None
                return f"Repair refused: {_text(row.get('reason')) or 'No reason reported.'}"
        if state.kind in (StateKind.WAITING_FOR_GAME, StateKind.REBUILDING):
            return f"Repair in progress: {state.reason}."
        self._repair_request = None
        if state.kind is StateKind.IDLE and state.game_update_classification == "current":
            self._repair_succeeded = True
            return "The farmer patch is ready. Run checks again to refresh these results."
        if state.kind is StateKind.FARMER_UNAVAILABLE:
            record = state.quarantine or {}
            detail = _text(record.get("detail")) if record.get("reason") == state.reason else ""
            reason = detail or _UPDATE_FAILURES.get(state.reason) or state.reason
            return f"Repair failed: {reason or 'The farmer patch is unavailable.'}"
        return "The service did not confirm repair. See Game update for the current state."

    def _diagnostics(self, state: ServiceState) -> DiagnosticsView:
        if self._repair_request is not None:
            self._repair_feedback = self._repair_status(state, self._repair_request)
        eligible = self._farmer_patch_failed() and not self._repair_succeeded and self._repair_request is None
        blocker = self._repair_blocker(state) if eligible else ""
        return DiagnosticsView(self._checks, self._check_error, self._repair_feedback, blocker,
                               eligible and not blocker)

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
        if view.can_pick_location and selected is not None:
            settings = replace(self._session_settings, location=location)
            if settings.tower is None and str(settings.difficulty) not in _difficulties(selected):
                settings = replace(settings, difficulty=None)
            self._session_settings = settings
            self._save_picks()

    def select_tower_floor(self, floor: int) -> None:
        view = self.poll()
        choice = self._session_settings.tower
        if view.can_pick_location and choice and choice["kind"] == "normal" and str(floor) in view.tower_floors:
            self._session_settings = replace(self._session_settings, location={**choice, "floor": floor})
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

    def set_keep_unowned_legendaries(self, enabled: bool) -> None:
        if self.poll().can_pick_run_choice:
            self._session_settings = replace(self._session_settings, keep_unowned_legendaries=enabled)
            self._save_picks()

    def set_experimental_speed(self, enabled: bool) -> None:
        if self.poll().can_pick_run_choice:
            self._session_settings = replace(self._session_settings, experimental_speed=enabled)
            self._save_picks()

    def set_maintenance(self, name: str, enabled: bool) -> None:
        if name in commands.MAINTENANCE_CONFIG_KEYS and self.poll().can_edit_maintenance:
            changes: dict[str, Any] = {name: enabled}
            self._session_settings = replace(self._session_settings, **changes)
            self._save_picks()

    def set_show_game_window(self, enabled: bool) -> None:
        if self.poll().can_change_show_game_window:
            self._session_settings = replace(self._session_settings, show_game_window=enabled)
            self._save_picks()

    def _selected_settings(self, view: SessionView, *, resuming: bool = False) -> commands.SessionSettings:
        settings = self._session_settings
        if view.tower_selected:
            return replace(settings, location=view.locations[view.location_index]["id"], difficulty=None, oaths={})
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

    def run_diagnostics(self) -> Callable[[], None]:
        """Run the I/O separately and return the update for the model worker."""
        try:
            checks = doctor.run_checks(self._os)
        except (OSError, RuntimeError) as exc:
            return partial(self._publish_checks, [], f"Could not run the diagnostic checks: {exc}")
        return partial(self._publish_checks, checks, "")

    def _publish_checks(self, checks: list[doctor.Check], error: str) -> None:
        self._checks, self._check_error = checks, error
        if not error:
            self._repair_succeeded = False
            if self._repair_request is None:
                self._repair_feedback = ""

    def repair_farmer_pack(self) -> Callable[[], None]:
        """Recheck live eligibility and queue the request outside the model worker."""
        try:
            request = doctor.repair_farmer_pack(self._os)
        except (OSError, RuntimeError) as exc:
            return partial(self._publish_repair, None, f"Could not request repair: {exc}")
        return partial(self._publish_repair, request, "")

    def _publish_repair(self, request: Path | None, feedback: str) -> None:
        self._repair_request, self._repair_feedback = request, feedback

    def check_app_updates(self) -> None:
        if not self.poll().updates.can_check_app:
            return
        try:
            app_update.request_update_check(self._os)
        except OSError:
            self._app_check_feedback = "Could not queue the App update check: app data is unavailable."
        else:
            self._app_check_feedback = ""

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
