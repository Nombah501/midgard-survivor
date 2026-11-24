"""On-demand local diagnostics; checks do not prepare or repair anything."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Literal, TypedDict

from ..platform import Platform
from . import _app_releases, game_update
from .commands import submit
from .config import read_config
from .farmer_patch import gdre
from .preflight import PreflightError
from .profile import AmbiguousProfile, ProfileNotFound, find_profile
from .state import ServiceState, StateKind, read_state


type CheckStatus = Literal["ok", "warn", "fail"]


class Check(TypedDict):
    id: str
    status: CheckStatus
    summary: str
    next_action: str


class RepairUnavailable(RuntimeError):
    """The service cannot safely accept a farmer patch repair now."""


_REPAIR = "With the game closed and no AFK session, use Game update → Check again (Repair farmer pack)."
_UPDATE = "Open the game, accept the official update, then close it and run Doctor again."
_NTFY = "Set ntfy_url in the app-data config.json for push notifications."
_CHANNEL = "Provision the signed update domain and public key as described in ADR 0010, then install that release."
_QUARANTINE_FIXES = {
    "app_data_unusable": "Check the app-data folder permissions and free space, then start the service.",
    "profile_unusable": "Check the game profile folder permissions and free space, then start the service.",
    "invalid_saved_session": "Review the preserved session diagnostics before starting a new AFK session.",
    "build_failed": "Review the build log and GDRE/cache checks, then use Game update → Check again.",
    "anchors_broken": "Install an App release compatible with this Game update, then use Game update → Check again.",
    "smoke_failed": "Review the sandbox smoke log, then use Game update → Check again after fixing the cause.",
    "preflight_failed": "Fix the failed Doctor checks and review the last attempt log before starting a new session.",
    "cfg_invalid": "Check the run choices and start a new AFK session.",
    "checkpoint_corrupt": "Preserve the logs and checkpoint; inspect the game save before starting a new session.",
    "flush_failed": "Check free space and profile access; verify the save in the game before starting again.",
}


def _check(id: str, status: CheckStatus, summary: str, next_action: str = "") -> Check:
    return {"id": id, "status": status, "summary": summary, "next_action": next_action}


def _game(os_: Platform) -> Check:
    guidance = ("Set GAME_DIR or an absolute game_dir in the app-data config.json, or run the game once with the "
                "service running so it learns the executable." if os_.release_os == "windows" else
                "Install the game in ~/games/midgard-survivors or set GAME_DIR to the game directory.")
    try:
        game = os_.game_executable_readonly()
        if game.is_file() and os.access(game, os.X_OK):
            return _check("game_install", "ok", f"Game executable: {game}")
        return _check("game_install", "fail", f"Game not found or not executable at {game}", guidance)
    except (OSError, RuntimeError, ValueError) as exc:
        return _check("game_install", "fail", f"Could not find the game executable: {exc}", guidance)


def _profile(os_: Platform) -> tuple[Check, Path | None]:
    try:
        profile = find_profile(os_.godot_user_data_root())
    except AmbiguousProfile as exc:
        return _check("profile", "fail", str(exc),
                      "Identify the active profile and archive other candidates outside Godot user data; do not delete saves."), None
    except ProfileNotFound as exc:
        return _check("profile", "fail", str(exc),
                      "Launch the game once to create the profile and accept the official update, then close it."), None
    except (OSError, RuntimeError) as exc:
        return _check("profile", "fail", f"Could not inspect game profiles: {exc}",
                      "Check access to the Godot user-data folder."), None
    return _check("profile", "ok", f"Game profile: {profile}"), profile


def _patches(os_: Platform, profile: Path | None) -> tuple[Check, Check]:
    if profile is None:
        return (_check("official_patch", "warn", "Official patch not checked without a unique profile.",
                       "Resolve the game profile check first."),
                _check("farmer_patch", "warn", "Farmer patch not checked without a unique profile.",
                       "Resolve the game profile check first."))
    unchecked = _check("farmer_patch", "warn", "Farmer patch not checked without an official patch.",
                       "Resolve the official patch check first.")
    try:
        patch = game_update.inspect_patch(os_, profile)
        if patch is None or not patch.official.is_file():
            return _check("official_patch", "fail", "No official patch found on disk.", _UPDATE), unchecked
    except (OSError, RuntimeError, PreflightError) as exc:
        return (_check("official_patch", "fail", f"Could not identify the official patch: {exc}",
                       "Check Game update diagnostics. If migrating a legacy checkout, restore the official patch first."),
                unchecked)
    official = _check("official_patch", "ok", f"Official patch: {patch.official.name}")
    try:
        issue = patch.integrity_issue()
    except (OSError, PreflightError) as exc:
        return official, _check("farmer_patch", "fail", f"Could not verify the patch digests: {exc}",
                                "Check read access to the patches and app-data folders, then rerun Doctor.")
    if issue:
        return official, _check("farmer_patch", "fail", issue, _REPAIR)
    return official, _check("farmer_patch", "ok", "Mounted farmer patch, official patch and bridge match the build digests.")


def _gdre(os_: Platform) -> Check:
    action = "Allow the next farmer patch build to fetch the pinned GDRE archive from GitHub."
    try:
        path = gdre.cached_archive(os_)
        actual = gdre.sha256(path)
    except FileNotFoundError:
        return _check("gdre", "warn", "Pinned GDRE archive is not cached.", action)
    except (OSError, RuntimeError) as exc:
        return _check("gdre", "fail", f"Could not read the GDRE cache: {exc}",
                      "Check permissions on the app-data gdre folder.")
    if actual != gdre.RELEASES[os_.release_os].sha256:
        return _check("gdre", "fail", "Cached GDRE archive does not match its pinned SHA-256.", action)
    return _check("gdre", "ok", "Pinned GDRE archive is cached and matches its SHA-256.")


def _network(os_: Platform) -> Check:
    try:
        warning = os_.check_network_isolation()
    except (OSError, subprocess.SubprocessError) as exc:
        return _check("network_isolation", "fail", str(exc),
                      "Install util-linux and enable unprivileged user and network namespaces for the service user.")
    if warning:
        return _check("network_isolation", "warn", warning,
                      "Accept game updates before farming. Never farm simultaneously against the same cloud-linked profile.")
    return _check("network_isolation", "ok", "unshare can create a user and network namespace.")


def _service(os_: Platform, state: ServiceState) -> Check:
    try:
        registered = os_.service_registered()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else None
        return _check("service", "fail", f"Could not query the service manager: {str(detail or exc).strip()}",
                      "Sign in normally and check the systemd user manager or Windows Task Scheduler.")
    if not registered:
        return _check("service", "fail", "Midgard Farm service is not registered.", "Run midgard-farm-setup.")
    if state.kind is StateKind.STALE:
        return _check("service", "fail", "Service is registered but is not publishing fresh state.",
                      "Use Start service in the window. If it is already running, check the service logs.")
    return _check("service", "ok", "Service is registered and publishing fresh state.")


def _disk(id: str, label: str, path: Path) -> Check:
    try:
        minimum = int(os.environ.get("FARMER_MIN_FREE_MB") or "200")
    except ValueError:
        return _check(id, "fail", f"Cannot assess free space on the {label} volume.",
                      "Set FARMER_MIN_FREE_MB to an integer or unset it to use the 200 MiB default.")
    # App data may not exist before setup. Ask the nearest existing parent without creating anything.
    for volume_path in (path, *path.parents):
        try:
            free = shutil.disk_usage(volume_path).free // (1024 * 1024)
        except FileNotFoundError:
            continue
        except OSError as exc:
            return _check(id, "fail", f"Could not check the {label} volume: {exc}", "Check access to this volume.")
        summary = f"{label}: {free:,} MiB free ({volume_path})."
        if free < minimum:
            return _check(id, "fail", summary, f"Free at least {minimum:,} MiB on this volume before farming.")
        return _check(id, "ok", summary)
    return _check(id, "fail", f"Could not find the {label} volume for {path}.", "Check that this volume is mounted.")


def _notifications(os_: Platform) -> Check:
    try:
        configured = bool(read_config(os_, strict=True).ntfy_url)
    except (ValueError, RuntimeError) as exc:
        return _check("notifications", "fail", str(exc), f"Correct the app-data config.json. {_NTFY}")
    if not configured:
        return _check("notifications", "warn", "Push notifications (ntfy_url) are not configured.", _NTFY)
    return _check("notifications", "ok", "Push notifications (ntfy_url) are configured; delivery was not tested.")


def _channel() -> Check:
    try:
        _app_releases.update_base_url()
    except (_app_releases.ReleaseError, ValueError):
        return _check("update_channel", "warn", "Signed App update domain is not configured.", _CHANNEL)
    if not _app_releases.MINISIGN_PUBLIC_KEY:
        return _check("update_channel", "warn", "Signed App update public key is not configured.", _CHANNEL)
    return _check("update_channel", "ok", "Signed App update domain and public key are configured; not contacted.")


def _quarantine(os_: Platform, state: ServiceState) -> Check:
    record = state.quarantine
    if record is None and state.kind is StateKind.STALE:
        # Startup can fail before there is a state publisher.
        try:
            path = os_.app_data_dir() / "quarantine.json"
        except RuntimeError as exc:
            return _check("quarantine", "fail", f"Could not locate the quarantine record: {exc}",
                          "Sign in with a valid app-data location.")
        try:
            record = json.loads(os_.read_shared(path))
            if not isinstance(record, dict):
                raise ValueError("expected a JSON object")
        except FileNotFoundError:
            pass
        except (OSError, ValueError, RecursionError):
            return _check("quarantine", "fail", f"Could not read the quarantine record at {path}.",
                          "Preserve the record and review the service logs.")
    if record is None:
        return _check("quarantine", "ok", "No current quarantine reported.")
    reason = record.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "unknown reason"
    if reason in {"invalid_location", "invalid_difficulty", "invalid_oath"}:
        fix = "Correct the run choice before starting a new AFK session."
    elif reason in _QUARANTINE_FIXES:
        fix = _QUARANTINE_FIXES[reason]
    else:
        fix = "Review the preserved supervisor logs and fix the last failure before starting a new AFK session."
    return _check("quarantine", "fail", f"Current quarantine: {reason}", fix)


def run_checks(os_: Platform) -> list[Check]:
    """Read a diagnostic snapshot; call on demand, not in a UI poll loop."""
    game = _game(os_)
    profile_check, profile = _profile(os_)
    official, farmer = _patches(os_, profile)
    try:
        state = read_state(os_)
    except (RuntimeError, RecursionError):
        state = ServiceState(StateKind.STALE, "Service state unavailable")
    try:
        app_disk = _disk("app_disk", "App data", os_.app_data_dir())
    except RuntimeError as exc:
        app_disk = _check("app_disk", "fail", str(exc), "Sign in with a valid app-data location.")
    profile_disk = (_disk("profile_disk", "Game profile", profile) if profile is not None else
                    _check("profile_disk", "warn", "Profile volume not checked without a unique profile.",
                           "Resolve the game profile check first."))
    return [game, profile_check, official, farmer, _gdre(os_), _network(os_), _service(os_, state), app_disk,
            profile_disk, _notifications(os_), _channel(), _quarantine(os_, state)]


def repair_farmer_pack(os_: Platform) -> Path:
    """Queue the service's digest-aware Check again; return the request path.

    Call only on an explicit operator request, with the running service idle
    and the game closed. The service owns all rebuild/smoke/install work.
    """
    state = read_state(os_)
    if state.session_id is not None or state.kind is StateKind.ACTIVE:
        raise RepairUnavailable("Finish the AFK session before repairing the farmer patch.")
    if state.kind in (StateKind.STALE, StateKind.REBUILDING, StateKind.UPDATING):
        raise RepairUnavailable("The service must be running and idle to repair the farmer patch.")
    try:
        (os_.app_data_dir() / "session.json").stat()
    except FileNotFoundError:
        pass
    else:
        raise RepairUnavailable("An unfinished AFK session exists; finish it before repairing the farmer patch.")
    if os_.game_pids():
        raise RepairUnavailable("Close the game before repairing the farmer patch.")
    return submit(os_, "check_again")
