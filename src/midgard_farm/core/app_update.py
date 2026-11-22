"""Coordinate verified App updates with the supervisor and an independent watchdog."""

import json
import math
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from ..platform import InstanceLock, LockHeld, Platform
from . import _app_releases as releases
from .commands import submit
from .config import read_config
from .history import append_event, read_history
from .install import remove_legacy_release_token
from .profile import ProfileNotFound, find_profile

CHECK_INTERVAL = 86400.0
_CHECK_REQUEST_POLL = 1.0
_CHECK_REQUEST = "app-update-check-request"
_CHECK_LOCK = "app-update-check.lock"
_SEQUENCE_FLOOR = "app-update-sequence.json"
READY_TIMEOUT = 60.0
HANDOFF_TIMEOUT = 15.0
POLL = 0.2
_PLATFORM_ERRORS = (OSError, RuntimeError, subprocess.SubprocessError)
type Notify = Callable[[str, str], None]
type CheckResult = Literal["up_to_date", "staged", "excluded", "error"]


def _load(os_: Platform, name: str) -> dict[str, Any]:
    try:
        raw = json.loads(os_.read_shared(os_.app_data_dir() / name))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, RecursionError):
        return {}


def _save(os_: Platform, name: str, payload: object) -> None:
    os_.write_atomic(os_.app_data_dir() / name, json.dumps(payload, allow_nan=False).encode())


def _version(value: object) -> str | None:
    return value if isinstance(value, str) and releases.version_key(value) is not None else None


def _selected(os_: Platform) -> str | None:
    try:
        return _version(os_.read_shared(os_.app_data_dir() / "current").decode().strip())
    except (OSError, UnicodeError):
        return None


def _executable(os_: Platform, version: str) -> Path:
    return os_.app_data_dir() / "versions" / version / ("midgard-farm-service" + os_.executable_suffix)


def request_update_check(os_: Platform) -> None:
    """Ask the installed service to check now; results are read via read_update_status."""
    os_.write_atomic(os_.app_data_dir() / _CHECK_REQUEST, b"")


def _check_pending(os_: Platform) -> bool:
    data = os_.app_data_dir()
    lock = data / _CHECK_LOCK
    try:
        if (data / _CHECK_REQUEST).is_file():
            return True
        if lock.is_file():
            with os_.acquire_lock(lock):
                return False
    except LockHeld:
        return True
    except OSError:
        pass
    return False


def _read_floor(os_: Platform) -> tuple[int, str]:
    try:
        payload = json.loads(os_.read_shared(os_.app_data_dir() / _SEQUENCE_FLOOR))
    except FileNotFoundError:
        return 0, ""
    except (OSError, ValueError, RecursionError):
        raise releases.ReleaseError("could not read the saved update sequence floor") from None
    if (not isinstance(payload, dict) or type(payload.get("sequence")) is not int
            or payload["sequence"] < 1 or not releases.is_sha256(payload.get("manifest_sha256"))):
        raise releases.ReleaseError("could not read the saved update sequence floor")
    return payload["sequence"], payload["manifest_sha256"]


def _unexpired(checked: dict[str, Any]) -> bool:
    expires_at = checked.get("expires_at")
    return type(expires_at) is int and expires_at > time.time()


@dataclass(frozen=True)
class UpdateStatus:
    version: str | None
    previous: str | None
    staged: str | None
    last_checked: float | None
    reason: str
    switching: bool
    switch_overdue: bool
    latest_version: str | None
    changelog: str
    last_result: CheckResult | None
    check_pending: bool


def read_update_status(os_: Platform) -> UpdateStatus:
    check_pending = _check_pending(os_)
    checked = _load(os_, "app-update-check.json")
    last = checked.get("last_checked")
    switch = _pending(os_)
    state = _load(os_, "app-update.json")
    staged = _version(checked.get("staged"))
    if staged in _bad(state) or staged == state.get("manual_hold") or not _unexpired(checked):
        staged = None
    cutoff = (switch.deadline or switch.created + HANDOFF_TIMEOUT) if switch else None
    return UpdateStatus(_selected(os_), _version(state.get("previous")), staged,
                        last if type(last) is float and math.isfinite(last) and 0 < last < 1e11 else None,
                        reason if isinstance(reason := checked.get("reason"), str) else "",
                        switch is not None, bool(cutoff and time.time() > cutoff),
                        _version(checked.get("latest_version")),
                        changelog if isinstance(changelog := checked.get("changelog"), str) else "",
                        result if (result := checked.get("last_result")) in
                        ("up_to_date", "staged", "excluded", "error") else None, check_pending)


@dataclass(frozen=True)
class _Switch:
    id: str
    source: str
    target: str
    manual: bool
    created: float
    deadline: float = 0.0
    launched: bool = False


def _pending(os_: Platform) -> _Switch | None:
    row = _load(os_, "app-update-pending.json")
    source, target = _version(row.get("source")), _version(row.get("target"))
    identifier, manual = row.get("id"), row.get("manual")
    created, deadline, launched = row.get("created"), row.get("deadline"), row.get("launched")
    if (source and target and source != target and isinstance(identifier, str) and len(identifier) == 32
            and all(c in "0123456789abcdef" for c in identifier) and type(manual) is bool
            and type(created) is float and math.isfinite(created) and created >= 0
            and type(deadline) is float and math.isfinite(deadline) and deadline >= 0
            and type(launched) is bool):
        return _Switch(identifier, source, target, manual, created, deadline, launched)
    return None


def _bad(state: dict[str, Any]) -> tuple[str, ...]:
    bad = state.get("bad")
    return tuple(version for item in bad if (version := _version(item))) if isinstance(bad, list) else ()


def _clear_pending(os_: Platform) -> None:
    (os_.app_data_dir() / "app-update-pending.json").unlink(missing_ok=True)


def _quiet(os_: Platform) -> bool:
    return not (os_.app_data_dir() / "session.json").exists() and not os_.game_running()


def _queue(os_: Platform, switch: _Switch) -> None:
    executable = _executable(os_, switch.source)
    if not executable.is_file():
        raise OSError("known-good service executable is missing")
    os_.queue_update_watchdog([str(executable.resolve()), "--app-update-handoff", switch.id])


class AppUpdater:
    """Check on a background thread; switch only on the supervisor's idle boundary."""

    def __init__(self, os_: Platform, version: str):
        self.os = os_
        self.version = version
        self.enabled = _selected(os_) == version and _version(version) is not None
        self._stop = threading.Event()
        self._started = False
        self._auto_refused: str | None = None

    def __enter__(self) -> "AppUpdater":
        if _pending(self.os) is None:
            self.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self._stop.set()

    def start(self) -> None:
        if self.enabled and not self._started:
            self._started = True
            threading.Thread(target=self._check_daily, name="app-update-check", daemon=True).start()

    def _check_daily(self) -> None:
        os_ = self.os
        data = os_.app_data_dir()
        request = data / _CHECK_REQUEST
        next_check = time.monotonic()
        while not self._stop.is_set():
            remaining = next_check - time.monotonic()
            try:
                if remaining > 0 and not request.is_file():
                    self._stop.wait(min(_CHECK_REQUEST_POLL, remaining))
                    continue
                with os_.acquire_lock(data / "app-update.lock"):
                    if _selected(os_) != self.version:
                        return
                    if _pending(os_) is None:
                        with os_.acquire_lock(data / _CHECK_LOCK):
                            request.unlink(missing_ok=True)
                            self._check_locked()
                        next_check = time.monotonic() + CHECK_INTERVAL
                        continue
            except (LockHeld, OSError):
                pass  # The watchdog, setup, or another check can temporarily own this boundary.
            self._stop.wait(_CHECK_REQUEST_POLL)

    def _check_locked(self) -> None:
        os_ = self.os
        prior = _load(os_, "app-update-check.json")
        result: dict[str, Any] = {key: prior[key] for key in ("latest_version", "changelog", "verified_assets")
                                  if key in prior}
        target = None
        try:
            remove_legacy_release_token(os_.app_data_dir())
            manifest, digest = releases.get_manifest()
            sequence, accepted_digest = _read_floor(os_)
            if manifest.sequence < sequence:
                raise releases.ReleaseError("update manifest sequence is below the saved floor")
            if manifest.sequence == sequence and digest != accepted_digest:
                raise releases.ReleaseError("update manifest sequence was reused")
            if manifest.sequence > sequence:
                # Advance on verified metadata even if downloading the archive fails.
                _save(os_, _SEQUENCE_FLOOR, {"sequence": manifest.sequence, "manifest_sha256": digest})
            result.update(latest_version=manifest.version, changelog=manifest.changelog, reason="",
                          manifest_sha256=digest, expires_at=manifest.expires_at)
            state = _load(os_, "app-update.json")
            latest = releases.version_key(manifest.version)
            current = releases.version_key(self.version)
            if latest is None or current is None or latest <= current:
                result["last_result"] = "up_to_date"
            elif manifest.version in _bad(state) or manifest.version == state.get("manual_hold"):
                result["last_result"] = "excluded"
            else:
                versions = os_.app_data_dir() / "versions"
                versions.mkdir(exist_ok=True)
                asset = manifest.archives[os_.release_os]
                verified = f"{asset.sha256}/{manifest.version}"
                if verified != result.get("verified_assets") or not releases.has_service(os_, versions / manifest.version):
                    releases.download(os_, manifest.version, asset, versions)
                if not _unexpired(result):
                    raise releases.ReleaseError("update manifest has expired")
                target = manifest.version
                result.update(last_result="staged", staged=target, verified_assets=verified)
        except (OSError, releases.ReleaseError) as exc:
            result.update(last_result="error", reason=str(exc) if isinstance(exc, releases.ReleaseError)
                          else "could not read or write local update data")
        if not self._stop.is_set():
            try:
                _save(os_, "app-update-check.json", {**result, "last_checked": time.time()})
            except OSError:
                return  # A temporarily unwritable data directory cannot publish a result.
            if result["last_result"] != "error":
                _prune(os_, self.version, target)

    def begin(self, *, manual: bool) -> tuple[bool, str]:
        """Return (handoff queued, refusal); a busy game leaves a request pending."""
        os_ = self.os
        if not self.enabled:
            return False, "App updates need an installed release."
        try:
            with os_.acquire_lock(os_.app_data_dir() / "app-update.lock"):
                if _pending(os_) is not None or _selected(os_) != self.version:
                    return False, ""
                prior = _load(os_, "app-update.json" if manual else "app-update-check.json")
                target = _version(prior.get("previous" if manual else "staged"))
                if not target or target == self.version or not releases.has_service(os_, _executable(os_, target).parent):
                    return False, "No previous app release is available." if manual else ""
                if not manual:
                    state = _load(os_, "app-update.json")
                    verified = prior.get("verified_assets")
                    key, base = releases.version_key(target), releases.version_key(self.version)
                    if (not key or not base or key <= base or not isinstance(verified, str)
                            or not verified.endswith("/" + target) or not releases.is_sha256(verified[:64])
                            or not _unexpired(prior) or prior.get("manifest_sha256") != _read_floor(os_)[1]
                            or target in _bad(state)
                            or target == state.get("manual_hold") or target == self._auto_refused):
                        return False, ""
                if not _quiet(os_):
                    return False, ""
                switch = _Switch(uuid.uuid4().hex, self.version, target, manual, time.time())
                _save(os_, "app-update-pending.json", asdict(switch))
        except (LockHeld, releases.ReleaseError):
            return False, ""
        try:
            _queue(os_, switch)
        except _PLATFORM_ERRORS:
            _clear_pending(os_)
            if not manual:
                self._auto_refused = target
            return False, "Could not start the App update watchdog."
        return True, ""


def recover_on_start(os_: Platform, version: str) -> bool:
    """Ensure a pending switch has a watchdog. Return true if the old process must exit."""
    switch = _pending(os_)
    if switch is None or _selected(os_) != version or version not in (switch.source, switch.target):
        return False
    if version == switch.target:
        _save(os_, "app-update-started.json", {"id": switch.id})
    restored = version == switch.source and _load(os_, "app-update.json").get("last_switch") == switch.id
    try:
        with os_.acquire_lock(os_.app_data_dir() / "app-update.lock"):
            if _pending(os_) == switch:
                _queue(os_, switch)
    except LockHeld:
        pass  # The original watchdog is still alive.
    return version == switch.source and not restored and _pending(os_) is not None


def report_ready(os_: Platform, version: str, stopping: Callable[[], bool]) -> bool:
    """Publish fresh readiness and don't process commands until the watchdog commits."""
    switch = _pending(os_)
    if switch is None or version not in (switch.source, switch.target) or _selected(os_) != version:
        return True
    target = version == switch.target
    instance = uuid.uuid4().hex
    lock = _readiness_lock(os_, instance)
    try:
        with os_.acquire_lock(lock) if target else nullcontext():
            if target:
                read_config(os_, strict=True)
                os_.check_network_isolation()
                _save(os_, "app-update-ready.json", {"id": switch.id, "version": version, "pid": os.getpid(),
                                                     "instance": instance, "at": time.time()})
            cutoff = time.monotonic() + READY_TIMEOUT + HANDOFF_TIMEOUT
            while _pending(os_) is not None and not stopping() and time.monotonic() < cutoff:
                time.sleep(POLL)
            return _pending(os_) is None and _selected(os_) == version and not stopping()
    finally:
        if target:
            try:
                lock.unlink(missing_ok=True)
            except OSError:
                pass  # An unlocked stale marker is never accepted.


def _ready(os_: Platform, switch: _Switch) -> bool:
    marker = _load(os_, "app-update-ready.json")
    at = marker.get("at")
    instance = marker.get("instance")
    if not (marker.get("id") == switch.id and marker.get("version") == switch.target
            and isinstance(instance, str) and len(instance) == 32 and all(c in "0123456789abcdef" for c in instance)
            and type(marker.get("pid")) is int and marker["pid"] > 0
            and type(at) is float and switch.deadline - READY_TIMEOUT <= at <= switch.deadline):
        return False
    lock = _readiness_lock(os_, instance)
    if lock.is_file():
        try:
            with os_.acquire_lock(lock):
                pass
        except LockHeld:
            return True
    return False


def _readiness_lock(os_: Platform, instance: str) -> Path:
    return os_.app_data_dir() / f"app-update-{instance}.lock"


def flush_history(os_: Platform) -> None:
    """Publish the watchdog's durable result while the serving process owns service.lock."""
    fields = _load(os_, "app-update.json").get("event")
    if not isinstance(fields, dict):
        return
    try:
        if not any(row.get("switch_id") == fields.get("switch_id") for row in read_history(os_)):
            append_event(os_, "app_update", **fields)
    except OSError:
        print("supervisor: could not record App update in history", flush=True)


def _prune(os_: Platform, *keep: str | None) -> None:
    versions = os_.app_data_dir() / "versions"
    state = _load(os_, "app-update.json")
    keep = (*keep, _selected(os_), _version(state.get("previous")))
    for directory in versions.iterdir():
        if directory.name not in keep and _version(directory.name) and directory.is_dir() and not directory.is_symlink():
            shutil.rmtree(directory, ignore_errors=True)  # A previous window may still hold Windows DLLs open.


def _wait_for_old_service(os_: Platform) -> InstanceLock:
    cutoff = time.monotonic() + HANDOFF_TIMEOUT
    while True:
        try:
            return os_.acquire_lock(os_.app_data_dir() / "service.lock")
        except LockHeld:
            if time.monotonic() >= cutoff:
                raise OSError("old service did not exit") from None
            time.sleep(POLL)


def run_watchdog(os_: Platform, identifier: str, notify: Notify) -> int:
    """Run from the known-good onedir, independently of both service generations."""
    data = os_.app_data_dir()
    try:
        with os_.acquire_lock(data / "app-update.lock"):
            switch = _pending(os_)
            if switch is None or switch.id != identifier:
                return 0
            _apply(os_, switch, notify)
            os_.clear_update_watchdog()
    except LockHeld:
        return 0  # Another watchdog has ownership; a duplicate request is harmless.
    except _PLATFORM_ERRORS:
        return 1  # Durable pending state is recovered by the next service start.
    return 0


def _apply(os_: Platform, switch: _Switch, notify: Notify) -> None:
    data = os_.app_data_dir()
    selected = _selected(os_)
    state = _load(os_, "app-update.json")
    cutoff = time.monotonic() + min(READY_TIMEOUT, max(0.0, switch.deadline - time.time()))
    if selected not in (switch.source, switch.target):
        _clear_pending(os_)  # Setup or the operator changed the selection independently.
        return
    if state.get("last_switch") == switch.id:
        event = state.get("event", {})
        ready = bool(event.get("ready"))
        if selected == switch.target or not ready:
            _finish(os_, switch, state, ready, notify, recovering=True)
        else:
            _clear_pending(os_)
        return
    if selected == switch.source and switch.deadline:
        # The deadline is durable before publication. No target was selected.
        _clear_pending(os_)
        os_.restart_service()
        return
    if selected == switch.source:
        try:
            with _wait_for_old_service(os_):
                profile = find_profile(os_.godot_user_data_root())
                with os_.acquire_lock(profile / "farmer_supervisor.lock"), os_.acquire_lock(profile / "farmer.run.lock"):
                    quiet = _quiet(os_)
                    if quiet:
                        switch = replace(switch, deadline=time.time() + READY_TIMEOUT)
                        cutoff = time.monotonic() + READY_TIMEOUT
                        _save(os_, "app-update-pending.json", asdict(switch))
                        os_.write_atomic(data / "current", (switch.target + "\n").encode())
        except (LockHeld, ProfileNotFound):
            quiet = False
        if not quiet:
            _clear_pending(os_)
            if switch.manual:
                submit(os_, "rollback_app")
            os_.restart_service()
            return
        try:
            os_.restart_service()
        except _PLATFORM_ERRORS:
            _finish(os_, switch, state, False, notify)
            return
        switch = replace(switch, launched=True)
        _save(os_, "app-update-pending.json", asdict(switch))
    ready = False
    while True:
        ready = _ready(os_, switch)
        if ready or time.monotonic() >= cutoff:
            break
        time.sleep(POLL)
    _finish(os_, switch, state, ready, notify)


def _finish(os_: Platform, switch: _Switch, state: dict, ready: bool, notify: Notify,
            *, recovering: bool = False) -> None:
    selected = _selected(os_)
    if selected != switch.target and not (recovering and not ready and selected == switch.source):
        _clear_pending(os_)
        return
    data = os_.app_data_dir()
    if not recovering:
        outcome = ("rolled back" if switch.manual else "installed") if ready else (
            "rollback failed" if switch.manual else "rolled back")
        if ready:
            state["previous"] = switch.source
            state["manual_hold"] = switch.source if switch.manual else None
        elif not switch.manual and _launch_was_attempted(os_, switch):
            state["bad"] = sorted(set(_bad(state)) | {switch.target})
        state["last_switch"] = switch.id
        state["event"] = {"outcome": outcome, "version": switch.target, "previous_version": switch.source,
                          "switch_id": switch.id, "detail": f"Version {switch.target}: {outcome}.", "ready": ready}
        _save(os_, "app-update.json", state)
    if not ready:
        if selected == switch.target:
            os_.write_atomic(data / "current", (switch.source + "\n").encode())
        if state.get("notified") != switch.id:
            message = (f"rollback to {switch.target} failed; restored {switch.source}" if switch.manual
                       else f"update to {switch.target} rolled back")
            notify("app_update_rolled_back", message)
            state["notified"] = switch.id
            _save(os_, "app-update.json", state)
        if not recovering or selected == switch.target or not _service_running(os_):
            os_.restart_service()
    _prune(os_, switch.source, switch.target if ready else None)
    _clear_pending(os_)


def _service_running(os_: Platform) -> bool:
    try:
        with os_.acquire_lock(os_.app_data_dir() / "service.lock"):
            return False
    except LockHeld:
        return True


def _launch_was_attempted(os_: Platform, switch: _Switch) -> bool:
    # The target publishes this before it acquires its readiness lock.
    if _load(os_, "app-update-started.json").get("id") == switch.id:
        return True
    if not switch.launched:
        return False
    try:
        return not os_.service_start_refused()
    except _PLATFORM_ERRORS:
        return True  # Only a definitive scheduler refusal overrides a queued restart.