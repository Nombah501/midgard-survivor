"""Run AFK sessions, own their terminal outcome and preserve their diagnostics."""

import json
import math
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Literal

from ..assets import modes_dir
from ..platform import NetworkIsolationError, Platform
from . import catalog, commands, farmer_patch, game_update
from .commands import Start
from .history import append_event, read_history, session_summary
from .launch import SHUTDOWN_GRACE_SECONDS, GameBusy, request_finish, run_attempt
from .preflight import PreflightError, read_launch_config
from .run_progress import (
    HEARTBEAT_INTERVAL,
    RAID_STALL_WINDOW,
    RUN_STALL_WINDOW,
    RUN_STALLED,
    STALE_HEARTBEAT_INTERVALS,
    Progress,
    RunProgress,
    in_raid,
)
from .state import StateKind, StateReporter, read_state

_INVALID_RUN_CHOICES = {
    "invalid_location", "invalid_difficulty", "invalid_oath",
    "tower_closed", "tower_hel_locked", "tower_invalid_floor", "tower_no_snapshot", "tower_intent_unresolved",
}
FATAL_REASONS = {"cfg_invalid", "checkpoint_corrupt", "flush_failed"} | _INVALID_RUN_CHOICES
POLL = 0.2
UPDATE_POLL = 1.0
UPDATE_FAILURES = tuple(game_update.FailureReason)
_SESSION_ACTIVE = "AFK session running"


def session_log_dir(os_: Platform, session_id: str) -> Path:
    """Return the supervisor's outcome and quarantine record directory for a valid session ID."""
    prefix, _, value = session_id.partition("-")
    if prefix not in ("afk", "verify") or len(value) != 32 or uuid.UUID(hex=value).hex != value:
        raise ValueError("invalid AFK session id")
    return os_.app_data_dir() / "logs" / f"supervisor-{session_id}"


class InvalidSavedSession(Exception):
    """A saved session cannot safely resume against the selected profile."""


def log(message: str) -> None:
    print(f"supervisor: {message}", flush=True)


def pending_commands(os_: Platform, state: StateReporter) -> Iterator[tuple[Path, commands.Command]]:
    for path in sorted(commands.directory(os_).glob("*.json")):
        payload = None
        try:
            payload = json.loads(os_.read_shared(path))
            command = commands.decode(payload)
        except FileNotFoundError:
            continue
        except (ValueError, RecursionError) as exc:
            action = payload.get("command") if isinstance(payload, dict) else None
            refuse_command(os_, state, path, action if isinstance(action, str) else "unknown", str(exc))
        else:
            yield path, command


def refuse_command(os_: Platform, state: StateReporter, path: Path, command: str, reason: str) -> None:
    rejection = commands.rejection_path(os_, path)
    rejection.parent.mkdir(parents=True, exist_ok=True)
    os_.write_atomic(rejection, json.dumps({"command": command, "reason": reason}).encode())
    for old in sorted(rejection.parent.glob("*.json"), reverse=True)[20:]:
        old.unlink(missing_ok=True)
    path.unlink()
    state.refusals_changed()
    log(f"refused {command} {path.name}: {reason}")


@dataclass(frozen=True)
class Policy:
    heartbeat_interval: float = HEARTBEAT_INTERVAL
    stale_intervals: int = STALE_HEARTBEAT_INTERVALS
    startup_grace: float = 180.0
    backoff_base: float = 15.0
    backoff_max: float = 600.0
    max_failures: int = 4
    failure_window: float = 3600.0
    kill_grace: float = 20.0
    stop_grace: float = SHUTDOWN_GRACE_SECONDS
    run_stall_window: float = RUN_STALL_WINDOW
    raid_stall_window: float = RAID_STALL_WINDOW

    @property
    def heartbeat_stale_after(self) -> float:
        return self.heartbeat_interval * self.stale_intervals


@dataclass(frozen=True)
class Attempt:
    number: int
    delay: float
    outcome: str
    reason: str
    exit_code: int | None
    detail: str = ""


@dataclass
class _Session:
    id: str
    start: Start
    request: str
    started_at: float | None
    paused: bool = False
    control_request: str | None = None
    attempts: list[Attempt] = field(default_factory=list)


@dataclass(frozen=True)
class _UpdateEvents:
    os: Platform
    reporter: StateReporter
    send_notification: Callable[[str, str], None]

    def classification(self, state: game_update.GameUpdateState) -> None:
        self.reporter.patch_status(game_update_classification=state.value)

    def state(self, kind: game_update.PipelineState, reason: str | None) -> None:
        if kind != "ready":
            self.reporter.set(StateKind(kind), reason or "")

    def history(self, event: dict[str, str]) -> None:
        fields = event.copy()
        append_event(self.os, fields.pop("kind"), **fields)

    def notify(self, event: str, message: str) -> None:
        self.send_notification(event, message)


class Supervisor:
    """Serve the command queue while holding the caller's service/profile locks."""

    def __init__(self, os_: Platform, profile: Path, policy: Policy,
                 stop_requested_at: Callable[[], float | None], notify: Callable[[str, str], None],
                 *, state: StateReporter, session_prefix: Literal["afk", "verify"] = "afk",
                 before_start: Callable[[], bool] = lambda: False, strategy: Path | None = None):
        self.os = os_
        self.profile = profile
        self.policy = policy
        self.stop_requested_at = stop_requested_at
        self.notify = notify
        self.state = state
        self.session_prefix = session_prefix
        self._before_start = before_start
        self._strategy = strategy  # Explicit strategy is for the sandbox verifier, not a service command.
        self._use_strategy_route = strategy is not None
        self._last_totals: dict = {}
        self.session_path = os_.app_data_dir() / "session.json"
        self.queue = commands.directory(os_)
        self.mailbox = profile / "farmer_command"
        self._update = game_update.GameUpdatePipeline(
            os_, profile, _UpdateEvents(os_, state, notify),
            stop_requested=lambda: stop_requested_at() is not None,
        )
        self._quarantine_path = self.session_path.parent / "quarantine.json"
        previous = read_state(os_)
        self._keep_official = previous.keep_official
        saved_quarantine = previous.quarantine
        self._update_quarantine = (saved_quarantine if saved_quarantine
                                   and saved_quarantine.get("reason") in UPDATE_FAILURES else None)
        self._preserve_session_quarantine = (
            saved_quarantine is not None and self._update_quarantine is None
            and (previous.last_outcome or {}).get("kind") == "quarantined"
            and (previous.last_outcome or {}).get("reason") == saved_quarantine.get("reason")
        )
        self._check_again = False

    def _recover_session(self) -> _Session | None:
        try:
            saved = json.loads(self.os.read_shared(self.session_path))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise InvalidSavedSession(f"{self.session_path}: {exc}") from exc
        if not isinstance(saved, dict):
            raise InvalidSavedSession(f"{self.session_path}: expected a JSON object")
        if saved.get("profile") != str(self.profile.absolute()):
            raise InvalidSavedSession(f"{self.session_path}: saved session belongs to a different profile")
        try:
            session_id = saved.get("id")
            prefix = f"{self.session_prefix}-"
            if not isinstance(session_id, str) or not session_id.startswith(prefix):
                raise ValueError("invalid saved AFK session id")
            session_log_dir(self.os, session_id)  # Validate before using a recovered ID.
            start = commands.decode(saved.get("start"))
            if not isinstance(start, Start):
                raise ValueError("saved AFK session has no Start command")
            request = saved.get("request")
            control_request = saved.get("control_request")
            if not isinstance(request, str):
                raise ValueError("invalid saved Start request name")
            for name in (request, control_request):
                if name is None:
                    continue
                if (not isinstance(name, str) or not name.endswith(".json")
                        or "\0" in name or Path(name).name != name or Path(name).anchor):
                    raise ValueError("invalid saved request name")
            paused = saved.get("paused", False)
            if type(paused) is not bool:
                raise ValueError("invalid saved pause state")
            started_at = saved.get("started_at")
            if started_at is not None and (type(started_at) not in (int, float) or not math.isfinite(started_at)):
                raise ValueError("invalid saved session start time")
            rows = saved.get("attempts", [])
            if not isinstance(rows, list):
                raise ValueError("invalid saved attempts")
            attempts = [Attempt(**row) for row in rows]
            if any(type(attempt.number) is not int or attempt.number < 1 or attempt.outcome != "failed"
                   for attempt in attempts):
                raise ValueError("invalid saved restart attempt")
        except (TypeError, ValueError, OverflowError) as exc:
            raise InvalidSavedSession(f"{self.session_path}: {exc}") from exc
        try:
            # Do not replay a Start or a control already committed before its acknowledgement.
            (self.queue / request).unlink(missing_ok=True)
            if control_request is not None:
                (self.queue / control_request).unlink(missing_ok=True)
        except OSError as exc:
            raise InvalidSavedSession(f"{self.session_path}: cannot acknowledge a saved request: {exc}") from exc
        return _Session(session_id, start, request, started_at, paused, control_request, attempts)

    def run(self) -> None:
        if session := self._recover_session():
            log(f"continuing unfinished session {session.id}")
            self._run_session(session, recovered_session=True)
        elif self.stop_requested_at() is None:
            if self._before_start():
                return
            self._idle_update()

        next_check = time.monotonic() + UPDATE_POLL
        while self.stop_requested_at() is None:
            if self._before_start():
                return
            for path, command in self._pending():
                if command == "restore_official":
                    self._restore_official(path)
                    continue
                if isinstance(command, Start) or command == "check_again":
                    self._keep_official = False
                    self.state.patch_status(keep_official=False, last_restore=None)
                gate = self._idle_update(check_again=command == "check_again")
                if isinstance(gate, game_update.Stopped) or self.stop_requested_at() is not None:
                    return
                next_check = time.monotonic() + UPDATE_POLL
                if command == "check_again":
                    path.unlink()
                    continue
                if isinstance(command, commands.Resume):
                    refuse_command(self.os, self.state, path, "resume", "Resume requires a paused AFK session.")
                    continue
                if not isinstance(command, Start):
                    log(f"ignoring {command}: no active AFK session")
                    path.unlink()
                    continue
                if isinstance(gate, (game_update.Quarantine, game_update.Blocked)):
                    refuse_command(self.os, self.state, path, "start", gate.reason)
                    continue
                if isinstance(gate, game_update.Wait) and self._update_quarantine is not None:
                    refuse_command(self.os, self.state, path, "start", self._update_quarantine["reason"])
                    continue
                if tower := command.settings.tower:
                    latest = catalog.tower_catalog(catalog.read_latest(self.os))
                    if reason := catalog.tower_blocker(latest, tower["kind"], tower["floor"]):
                        refuse_command(self.os, self.state, path, "start", reason)
                        continue
                if self._before_start():
                    return
                session = _Session(f"{self.session_prefix}-{uuid.uuid4().hex}", command, path.name, time.time())
                self._save_session(session)
                path.unlink()
                self._run_session(session)
                break
            else:
                if time.monotonic() >= next_check:
                    self._idle_update()
                    next_check = time.monotonic() + UPDATE_POLL
                time.sleep(POLL)

    def _write(self, path: Path, data: dict) -> None:
        self.os.write_atomic(path, json.dumps(data, indent=2).encode())

    def _save_session(self, session: _Session) -> None:
        self._write(self.session_path, {"id": session.id, "start": session.start.payload(),
                                       "profile": str(self.profile.absolute()), "request": session.request,
                                       "started_at": session.started_at, "paused": session.paused,
                                       "control_request": session.control_request,
                                       "attempts": [asdict(attempt) for attempt in session.attempts]})

    def _apply_control(self, session: _Session, path: Path, command: commands.Resume | Literal["pause", "resume"],
                       *, live: bool) -> None:
        start = session.start
        if isinstance(command, commands.Resume):
            if start.settings.tower != command.settings.tower:
                refuse_command(self.os, self.state, path, "resume", "Finish this session and Start to change a Tower choice.")
                return
            previous_mode = start.settings.mode
            start = replace(start, settings=command.settings)
            if live:
                config_path = self.profile / "farmer.cfg"
                try:
                    config = json.loads(self.os.read_shared(config_path))
                    if not isinstance(config, dict):
                        raise ValueError("farmer.cfg must be a JSON object")
                    if self._strategy is None and previous_mode != command.settings.mode:
                        strategy, _ = read_launch_config(modes_dir() / f"{command.settings.mode}.json", strategy=True)
                        # The running child keeps its character and effective display mode.
                        strategy.update({key: config[key] for key in ("class", "job_paths", "display") if key in config})
                        config = strategy
                    self._write(config_path, config | command.settings.config())
                except (OSError, ValueError, RecursionError, PreflightError) as exc:
                    # Settings are not committed or delivered if the config could not be prepared.
                    refuse_command(self.os, self.state, path, "resume", f"Cannot update farmer.cfg: {exc}")
                    return
        updated = replace(session, start=start, paused=command == "pause", control_request=path.name)
        # Commit before acknowledgement or delivery: the next child can boot
        # with the same intent even if this child never sees its mailbox.
        self._save_session(updated)
        if isinstance(command, commands.Resume):
            self._use_strategy_route = False
        session.start, session.paused, session.control_request = start, updated.paused, path.name
        path.unlink()
        if live:
            action = "resume_settings" if isinstance(command, commands.Resume) else command
            self.os.write_atomic(self.mailbox, (action + "\n").encode())

    def _restore_official(self, path: Path) -> None:
        try:
            farmer_patch.restore(self.os, self.profile)
        except farmer_patch.GameRunning:
            refuse_command(self.os, self.state, path, "restore_official",
                           "Close the game before restoring the official patch.")
            return
        except farmer_patch.OfficialPatchMissing:
            outcome, reason = "official_patch_missing", game_update.START_GAME_AND_UPDATE
            self.state.patch_status(game_update_classification=game_update.GameUpdateState.GAME_REINSTALL.value)
            self.state.set(StateKind.FARMER_UNAVAILABLE, reason)
        except (farmer_patch.PatchStateError, OSError) as exc:
            outcome, reason = "restore_failed", f"Could not restore the official patch: {exc}"
        else:
            outcome, reason = "restored", "Official patch restored."
            # Otherwise the next idle check would immediately reinstall the farmer patch.
            self._keep_official = True
        record = {"request": path.name, "outcome": outcome, "reason": reason}
        try:
            append_event(self.os, "game_update", action="restore_official", **record)
        except (OSError, ValueError) as exc:
            log(f"could not record official patch restoration in history: {exc}")
        self.state.patch_status(last_restore=record, keep_official=self._keep_official)
        path.unlink()
        if outcome == "restored":
            self._idle_update()

    def _idle_update(self, *, check_again: bool = False) -> game_update.PipelineResult | None:
        try:
            return self._check_update(check_again=check_again)
        except PreflightError as exc:
            # Surface the prerequisite without starting a session. A Start still
            # takes the same fatal preflight path as any other exit 78.
            self.state.set(StateKind.FARMER_UNAVAILABLE, str(exc))
            return None

    def _check_update(
        self, *, session: bool = False, check_again: bool = False, unattended: bool = False,
    ) -> game_update.PipelineResult:
        check_again = check_again or self._check_again
        self._check_again = False
        if check_again and self._update_quarantine is not None:
            self._clear_update_quarantine()
            self._publish_update_state(StateKind.REBUILDING, "checking for a Game update")
        prepare = session or not self._keep_official
        result = self._update.run(check_again=check_again, unattended=unattended and not check_again,
                                  prepare=prepare, allow_digest_repair=not session)
        if isinstance(result, game_update.Ready):
            kind = StateKind.ACTIVE if session else StateKind.IDLE
            reason = "AFK session in progress" if session else ""
            if prepare and self._update_quarantine is not None:
                self._clear_update_quarantine()
                self._publish_update_state(kind, reason)
            else:
                self.state.set(kind, reason)
        elif (isinstance(result, (game_update.Quarantine, game_update.Blocked))
              and result.reason in UPDATE_FAILURES):
            record = self._update_record(result)
            keys = ("reason", "detail", "log_path")
            if self._update_quarantine is None or any(self._update_quarantine.get(key) != record[key] for key in keys):
                # The Game update journal persists this block independently of the AFK outcome.
                if not self._preserve_session_quarantine:
                    self._write(self._quarantine_path, record)
                self._update_quarantine = record
            self._publish_update_state(StateKind.FARMER_UNAVAILABLE, result.reason)
        elif isinstance(result, game_update.Blocked) and self._update_quarantine is not None:
            self._clear_update_quarantine()
            self._publish_update_state(StateKind.FARMER_UNAVAILABLE, result.reason)
        return result

    def _publish_update_state(self, kind: StateKind, reason: str) -> None:
        if self._preserve_session_quarantine:
            self.state.set(kind, reason)
        else:
            self.state.set(kind, reason, quarantine=self._update_quarantine)

    def _clear_update_quarantine(self) -> None:
        self._quarantine_path.unlink(missing_ok=True)
        self._update_quarantine = None

    @staticmethod
    def _update_record(result: game_update.Quarantine | game_update.Blocked) -> dict:
        return {"reason": result.reason, "detail": result.detail, "next_action": "Check again", "attempts": [],
                "log_path": str(result.log_path) if result.log_path else None}

    def _pending(self) -> Iterator[tuple[Path, commands.Command]]:
        return ((path, command) for path, command in pending_commands(self.os, self.state)
                if command != "rollback_app")

    def _refuse_start(self, path: Path) -> None:
        refuse_command(self.os, self.state, path, "start", "AFK session already active")

    def _recover_outcome(self, log_dir: Path, session_id: str) -> tuple[dict, dict | None] | None:
        path = log_dir / "outcome.json"
        quarantine_path = log_dir / "quarantine.json"
        try:
            try:
                outcome = json.loads(self.os.read_shared(path))
            except FileNotFoundError:
                if not quarantine_path.exists():
                    return None  # Neither terminal record has been committed.
                raise
            if (not isinstance(outcome, dict) or outcome.get("session") != session_id
                    or outcome.get("kind") not in ("finished", "stopped", "quarantined")
                    or not isinstance(outcome.get("reason"), str) or not isinstance(outcome.get("attempts"), list)
                    or ("totals" in outcome and not isinstance(outcome["totals"], dict))
                    or ("ended_at" in outcome and type(outcome["ended_at"]) not in (int, float))):
                raise ValueError("invalid terminal outcome")
            quarantine = None
            if outcome["kind"] == "quarantined":
                if "quarantine" in outcome:
                    quarantine = outcome["quarantine"]
                else:  # Older supervisors committed a separate record.
                    path = quarantine_path
                    quarantine = json.loads(self.os.read_shared(path))
                if (not isinstance(quarantine, dict) or quarantine.get("reason") != outcome["reason"]
                        or not isinstance(quarantine.get("detail"), str)
                        or not isinstance(quarantine.get("attempts"), list)):
                    raise ValueError("invalid quarantine record")
        except (OSError, ValueError, RecursionError) as exc:
            raise InvalidSavedSession(f"{path}: {exc}") from exc
        return outcome, quarantine

    def _run_session(self, session: _Session, *, recovered_session: bool = False) -> None:
        session_id, request = session.id, session.request
        log_dir = session_log_dir(self.os, session_id)
        log_dir.mkdir(parents=True, exist_ok=True)
        outcome_path = log_dir / "outcome.json"
        if (recovered := self._recover_outcome(log_dir, session_id)) is not None:
            # Publishing an outcome commits the session even if it never reached history.
            outcome, quarantine = recovered
            self._append_outcome(outcome, log_dir, recovering=True)
            self._publish_outcome(outcome, log_dir, quarantine, request)
            return
        if self._update_quarantine is None:
            self._quarantine_path.unlink(missing_ok=True)
        self._preserve_session_quarantine = False
        self.state.set(StateKind.ACTIVE, "AFK session in progress", session_id=session_id, quarantine=None,
                       last_heartbeat=None, farmer_phase=None, refusals_superseded_through=request,
                       heartbeat_stale_after=self.policy.heartbeat_stale_after)
        self._last_totals = {}
        try:
            status = json.loads(self.os.read_shared(self.profile / "farmer_status.json"))
        except (OSError, ValueError):
            pass  # An attempt may never have started or written a readable status.
        else:
            if isinstance(status, dict) and status.get("session") == session_id:
                self._remember_totals(status)

        attempts = session.attempts
        failures: deque[float] = deque()
        number = max([attempt.number for attempt in attempts] +
                     [int(p.stem.removeprefix("attempt-")) for p in log_dir.glob("attempt-*.log")], default=0)
        delay = 0.0
        kind, reason = "stopped", "operator"
        update_quarantine = None
        while self.stop_requested_at() is None:
            if delay:
                log(f"restart in {delay:.1f}s")
                restart = f"Restarting in {delay:.1f}s"
                if attempts[-1].reason == RUN_STALLED:
                    restart = f"Run stalled · {restart}"
                self.state.set(StateKind.ACTIVE, restart, farmer_phase=None)
                if stopped := self._backoff(delay, session):
                    reason = stopped
                    break
                self.state.set(StateKind.ACTIVE, "AFK session in progress")
            preflight_error = None
            next_check = 0.0
            while self.stop_requested_at() is None:
                if time.monotonic() < next_check:
                    if stopped := self._between_attempts_commands(session):
                        reason = stopped
                        break
                    time.sleep(POLL)
                    continue
                try:
                    gate = self._check_update(session=True, unattended=recovered_session or bool(attempts))
                except PreflightError as exc:
                    preflight_error = exc
                    break
                if isinstance(gate, (game_update.Ready, game_update.Stopped)):
                    break
                if isinstance(gate, (game_update.Quarantine, game_update.Blocked)):
                    if gate.reason in UPDATE_FAILURES:
                        kind, update_quarantine = "quarantined", self._update_record(gate)
                    reason = gate.reason
                    break
                next_check = time.monotonic() + UPDATE_POLL
            if reason != "operator" or self.stop_requested_at() is not None:
                break
            number += 1
            attempt = self._attempt(session, log_dir, number, delay, preflight_error=preflight_error)
            attempts.append(attempt)
            if attempt.outcome == "finished":
                kind, reason = "finished", attempt.reason
                break
            if attempt.outcome == "stopped" or self.stop_requested_at() is not None:
                reason = attempt.reason
                break
            if attempt.outcome == "fatal":
                kind, reason = "quarantined", attempt.reason
                break
            now = time.monotonic()
            failures.append(now)
            while now - failures[0] > self.policy.failure_window:
                failures.popleft()
            if len(failures) >= self.policy.max_failures:
                kind = "quarantined"
                reason = f"{len(failures)} failures in {self.policy.failure_window:.0f}s"
                break
            self._save_session(session)
            self.notify("fail", f"farmer failed: {attempt.reason}; restarting")
            delay = min(self.policy.backoff_max, self.policy.backoff_base * 2 ** (len(failures) - 1))

        # A restore may have arrived during blocking rebuild or terminal process cleanup.
        for path, command in self._pending():
            if command == "restore_official":
                refuse_command(self.os, self.state, path, command, _SESSION_ACTIVE)

        diagnostics = [asdict(attempt) for attempt in attempts]
        quarantine = None
        if kind == "quarantined":
            if update_quarantine is not None:
                quarantine = {**update_quarantine, "attempts": diagnostics}
            else:
                last = attempts[-1]
                quarantine = {"reason": reason, "last_failure": last.reason, "detail": last.detail,
                              "attempts": diagnostics}
        outcome = {"session": session_id, "kind": kind, "reason": reason, "attempts": diagnostics,
                   **session_summary(self.os, self.profile, session_id, self._last_totals),
                   "ended_at": time.time()}
        if quarantine is not None:
            outcome["quarantine"] = quarantine
        if session.started_at is not None:
            outcome["started_at"] = session.started_at
        outcome["restarts"] = max(0, number - 1)
        outcome["attempt_failure_count"] = sum(attempt.outcome in ("failed", "fatal") for attempt in attempts)
        self._write(outcome_path, outcome)
        self._append_outcome(outcome, log_dir)
        self._publish_outcome(outcome, log_dir, quarantine, request)
        if kind == "quarantined":
            if update_quarantine is None and quarantine is not None:
                self.notify("quarantine", f"farmer quarantined: {reason} (last: {quarantine['detail'] or reason})")
        elif kind == "finished":
            self.notify("goal" if reason == "goal" else "stop", f"farmer finished: {reason}")
        elif reason != game_update.START_GAME_AND_UPDATE:
            self.notify("stop", f"supervisor stopped by operator: {reason}")
        log(f"session {kind}: {reason} after {len(attempts)} attempt(s); diagnostics in {log_dir}")

    def _append_outcome(self, outcome: dict, log_dir: Path, *, recovering: bool = False) -> None:
        try:
            if recovering and any(row["kind"] == "session" and row.get("session_id") == outcome["session"]
                                  for row in read_history(self.os)):
                return
            if "run_choices" not in outcome:  # Recover terminal records from older versions.
                summary = session_summary(self.os, self.profile, outcome["session"], outcome.get("totals", {}))
                outcome.setdefault("totals", summary["totals"])
                outcome["run_choices"] = summary["run_choices"]
            timing = {"timestamp": outcome["ended_at"]} if "ended_at" in outcome else {}
            metrics = {key: outcome[key] for key in ("started_at", "restarts", "attempt_failure_count")
                       if key in outcome}
            failures = dict.fromkeys(attempt["reason"] for attempt in outcome["attempts"]
                                     if isinstance(attempt, dict) and attempt.get("outcome") == "failed"
                                     and isinstance(attempt.get("reason"), str))
            append_event(self.os, "session", session_id=outcome["session"], outcome=outcome["kind"],
                         reason=outcome["reason"], totals=outcome["totals"], run_choices=outcome["run_choices"],
                         attempt_failures=list(failures),
                         diagnostics=log_dir.relative_to(self.session_path.parent).as_posix(), **timing, **metrics)
        except (OSError, ValueError) as exc:
            log(f"could not record AFK session {outcome['session']} in history: {exc}")
            self.notify("history_failed", f"Could not save AFK session history. Outcome saved in {log_dir}.")

    def _publish_outcome(self, outcome: dict, log_dir: Path, quarantine: dict | None, request: str) -> None:
        if quarantine is not None:
            # A diagnostic copy for existing consumers, not part of the commit.
            try:
                self._write(log_dir / "quarantine.json", quarantine)
            except OSError as exc:
                log(f"could not copy quarantine evidence from outcome.json: {exc}")
            quarantine = {**quarantine, "diagnostics": log_dir.relative_to(self.session_path.parent).as_posix()}
            if quarantine["reason"] in UPDATE_FAILURES:
                self._write(self._quarantine_path, quarantine)
                self._update_quarantine = quarantine
        self._preserve_session_quarantine = quarantine is not None and quarantine["reason"] not in UPDATE_FAILURES
        unavailable = (outcome["reason"] == game_update.START_GAME_AND_UPDATE
                       or (quarantine is not None and quarantine["reason"] in UPDATE_FAILURES))
        self.state.set(StateKind.FARMER_UNAVAILABLE if unavailable else StateKind.IDLE,
                       outcome["reason"] if unavailable else "", session_id=None, farmer_phase=None,
                       last_outcome=outcome, quarantine=quarantine, refusals_superseded_through=request)
        self.session_path.unlink()

    def _remember_totals(self, status: dict) -> None:
        if isinstance(totals := status.get("totals"), dict):
            self._last_totals = totals

    def _backoff(self, delay: float, session: _Session) -> str | None:
        deadline = time.monotonic() + delay
        while (left := deadline - time.monotonic()) > 0:
            if self.stop_requested_at() is not None:
                return "operator"
            if stopped := self._between_attempts_commands(session):
                return stopped
            time.sleep(min(left, POLL))
        return "operator" if self.stop_requested_at() is not None else None

    def _between_attempts_commands(self, session: _Session) -> str | None:
        for path, command in self._pending():
            if isinstance(command, Start):
                self._refuse_start(path)
                continue
            if isinstance(command, commands.Resume) or command in ("pause", "resume"):
                if isinstance(command, commands.Resume) and not session.paused:
                    refuse_command(self.os, self.state, path, "resume", "Resume requires a paused AFK session.")
                else:
                    self._apply_control(session, path, command, live=False)
                continue
            if command == "restore_official":
                refuse_command(self.os, self.state, path, command, _SESSION_ACTIVE)
                continue
            path.unlink()
            if command in ("finish", "abort"):
                return command
            if command == "check_again":
                self._check_again = True
            else:
                log(f"ignoring {path.name}: AFK session is between attempts")
        return None

    def _attempt(self, session: _Session, log_dir: Path, number: int, delay: float,
                 *, preflight_error: PreflightError | None) -> Attempt:
        start = session.start
        log_path = log_dir / f"attempt-{number:02d}.log"
        log(f"attempt {number}: {self._strategy or start.settings.mode}")
        launcher_detail = ""
        try:
            if preflight_error is not None:
                raise preflight_error
            result = run_attempt(self.os, self.profile, self._strategy, session.id, character=start.character,
                                 settings=start.settings, use_strategy_route=self._use_strategy_route,
                                 paused=session.paused, log_path=log_path,
                                 watch=self._watcher(session),
                                 poll_interval=max(0.05, min(POLL, self.policy.heartbeat_interval / 5)))
        except (PreflightError, NetworkIsolationError) as exc:
            launcher_detail = f"run: {exc}"
            attempt = Attempt(number, delay, "fatal", "preflight_failed", 78, launcher_detail)
        except (GameBusy, OSError) as exc:
            launcher_detail = str(exc)
            attempt = Attempt(number, delay, "failed", "exit_1_no_status", 1, launcher_detail)
        else:
            status = result.last_status or {}
            if status:
                self.state.observe_farmer(status)
                self._remember_totals(status)
            reason = str(status.get("finish_reason") or "")
            detail = ""
            if result.forced_reason:
                kind = "stopped" if result.forced_reason == "operator_timeout" else "failed"
                reason = result.forced_reason
                if reason == RUN_STALLED:
                    raid = in_raid(status.get("game"))
                    window = self.policy.raid_stall_window if raid else self.policy.run_stall_window
                    detail = f"Run stalled{' in a raid' if raid else ''}: game time did not advance for {window:g} s."
            elif result.clean(self.os):
                kind, reason = "finished", reason or "done"
            elif result.code == 78 and (self.os.game_exit_status_reliable or status.get("terminal") is not True):
                kind, reason = "fatal", "preflight_failed"
                detail = "run: attempt exited 78 without a preflight message"
                with log_path.open(encoding="utf-8", errors="replace") as file:
                    for line in file:
                        if line.startswith("run: "):
                            detail = line.rstrip()
            elif status.get("terminal") is True and status.get("failed") and reason:
                kind = "fatal" if reason in FATAL_REASONS else "failed"
                if reason in _INVALID_RUN_CHOICES or reason == "flush_failed":
                    detail = str(status.get("last_error") or reason)
            else:
                suffix = f"phase_{status.get('phase', '')}" if status else "no_status"
                kind, reason = "failed", f"exit_{result.code}_{suffix}"
            if kind != "finished" and status:
                self._write(log_path.with_suffix(".status.json"), status)
            attempt = Attempt(number, delay, kind, reason, result.code, detail)
        if launcher_detail:
            with log_path.open("a", encoding="utf-8") as file:
                print(launcher_detail, file=file)
        log(f"attempt {number}: {attempt.outcome} ({attempt.reason}, exit {attempt.exit_code}) {attempt.detail}".rstrip())
        return attempt

    def _watcher(self, session: _Session | None = None) -> Callable[[dict | None], str | None]:
        last_seq = last_change = terminal_at = None
        finish_sent = finish_before_boot = False
        closing = False
        run_progress = RunProgress(self.policy.run_stall_window, self.policy.raid_stall_window)

        def watch(status: dict | None) -> str | None:
            nonlocal last_seq, last_change, terminal_at, finish_sent, finish_before_boot
            nonlocal closing
            now = time.monotonic()
            if last_change is None:
                last_change = now
            progress = run_progress.observe(status, now)
            if status is not None:
                seq = status.get("heartbeat_seq")
                if type(seq) is int and seq != last_seq:
                    last_seq, last_change = seq, now
                    self.state.observe_farmer(status, run_progress=run_progress.snapshot(now, time.time()))
                    self._remember_totals(status)
                if status.get("terminal") is True and terminal_at is None:
                    terminal_at = now

            if (requested_at := self.stop_requested_at()) is not None:
                # The legacy alias is a finish request, not a signal to the game.
                if terminal_at is None and (not finish_sent or (finish_before_boot and status is not None)):
                    request_finish(self.profile)
                    log("requested finish")
                    finish_sent, finish_before_boot = True, status is None
                if now >= requested_at + self.policy.stop_grace:
                    return "operator_timeout"
            elif terminal_at is None and not self.mailbox.exists():
                for path, command in self._pending():
                    if isinstance(command, Start):
                        if closing:
                            # This Start follows Finish/Abort; let the idle service consume it.
                            break
                        self._refuse_start(path)
                        continue
                    if command in ("check_again", "restore_official"):
                        refuse_command(self.os, self.state, path, command, _SESSION_ACTIVE)
                        continue
                    if isinstance(command, commands.Resume):
                        phase = status.get("phase") if status else None
                        if not closing and session is not None and session.paused and phase in (None, "boot"):
                            break  # A paused child is still booting; do not refuse its Resume.
                        if closing or phase != "paused" or session is None:
                            refuse_command(self.os, self.state, path, "resume", "Resume requires a paused AFK session.")
                            continue
                    if isinstance(command, commands.Resume) or command in ("pause", "resume"):
                        if session is None:
                            continue
                        self._apply_control(session, path, command, live=True)
                        break
                    self.os.write_atomic(self.mailbox, (command + "\n").encode())
                    closing = closing or command in ("finish", "abort")
                    path.unlink()
                    break

            if terminal_at is not None:
                if now - terminal_at > self.policy.kill_grace:
                    return "no_exit_after_terminal"
            elif requested_at is None:
                if last_seq is None and now - last_change > self.policy.startup_grace:
                    return "no_heartbeat"
                if last_seq is not None and now - last_change > self.policy.heartbeat_stale_after:
                    return "heartbeat_stale"
                if last_seq is not None and progress is Progress.STALLED:
                    return RUN_STALLED
            return None

        return watch
