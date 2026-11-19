"""Classify and prepare the farmer patch before a supervised attempt."""

import json
import os
import time
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol

from ..platform import Platform
from . import farmer_patch, patch_info, smoke
from .farmer_patch._state import (
    OFFICIAL_STATE, STATE, bridge_name, official_name, patch_name, patch_version, read_state,
)
from .farmer_patch.gdre import Gdre
from .patch_info import INSTALLED_PACK, PatchInfo, PatchInfoError
from .preflight import PreflightError, sha256


class GameUpdateState(StrEnum):
    CURRENT = "current"
    GAME_UPDATE = "game_update"
    FARMER_REMOVED_OR_STALE = "farmer_removed_or_stale"
    GAME_REINSTALL = "game_reinstall"


@dataclass(frozen=True)
class _MountedPatch:
    official: Path
    mounted: bool
    same_base: bool
    info: PatchInfo | None

    def classify(self, fingerprint: str) -> GameUpdateState:
        if not self.mounted and not self.same_base:
            return GameUpdateState.GAME_UPDATE
        if (self.same_base and self.info is not None and self.info.farmer_hash == fingerprint
                and self.mounted and (self.official.parent / INSTALLED_PACK).is_file()):
            return GameUpdateState.CURRENT
        return GameUpdateState.FARMER_REMOVED_OR_STALE


def _read_shared(os_: Platform, path: Path) -> bytes:
    return os_.read_shared(path)


def _inspect(os_: Platform, profile: Path) -> _MountedPatch | None:
    patches = profile / "patches"
    state_path = patches / STATE
    try:
        raw = _read_shared(os_, state_path)
        if not raw.strip():
            return None
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError("expected a JSON object")
        if not state:
            return None
        mounted = patch_name(state.get("file")) == INSTALLED_PACK
        official = read_state(patches / OFFICIAL_STATE)[1] if mounted else state
        identity = official_name(official), patch_version(state), bridge_name(state)
    except FileNotFoundError:
        # read_state wraps errors from the saved official snapshot; only state.json is optional.
        return None
    except (OSError, ValueError, farmer_patch.PatchStateError) as exc:
        raise PreflightError(f"invalid patch state at {state_path}: {exc}") from exc
    try:
        info = patch_info.load(patch_info.info_path(os_))
    except PatchInfoError:
        info = None
    same_base = info is not None and identity == (info.patch_file, info.patch_version, info.bridge_file)
    return _MountedPatch(patches / identity[0], mounted, same_base, info)


def _farmer_hash(sources: Path | None) -> str:
    try:
        return farmer_patch.farmer_hash(sources)
    except (OSError, ValueError) as exc:
        raise PreflightError(f"cannot read farmer build inputs: {exc}") from exc


def classify(os_: Platform, profile: Path) -> GameUpdateState:
    """Read state and app metadata, not the contents of any game pack."""
    mounted = _inspect(os_, profile)
    return mounted.classify(_farmer_hash(None)) if mounted is not None else GameUpdateState.GAME_REINSTALL


GAME_CLOSE_GRACE_SECONDS = 3.0
WAITING_FOR_GAME = "waiting for the game to close"
START_GAME_AND_UPDATE = "start the game and accept the update"

type PipelineState = Literal["ready", "waiting_for_game", "rebuilding", "farmer_unavailable"]


class FailureReason(StrEnum):
    BUILD_FAILED = "build_failed"
    ANCHORS_BROKEN = "anchors_broken"
    SMOKE_FAILED = "smoke_failed"


class PipelineEvents(Protocol):
    def state(self, kind: PipelineState, reason: str | None) -> None: ...
    def history(self, event: dict[str, str]) -> None: ...
    def notify(self, event: str, message: str) -> None: ...


@dataclass(frozen=True)
class Ready:
    """The supervisor may proceed to normal launch preflight."""


@dataclass(frozen=True)
class Wait:
    reason: str


@dataclass(frozen=True)
class Blocked:
    reason: str
    detail: str = ""
    log_path: Path | None = None


@dataclass(frozen=True)
class Quarantine:
    reason: FailureReason
    detail: str
    log_path: Path | None


type PipelineResult = Ready | Wait | Blocked | Quarantine


class _Stage(StrEnum):
    BUILD = "build"
    SMOKE = "smoke"
    INSTALL = "install"
    RESTORE = "restore"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class _Transaction:
    official_patch_sha256: str
    farmer_hash: str
    classification: GameUpdateState
    stage: _Stage
    reason: FailureReason | None = None
    detail: str = ""
    log_path: str | None = None
    unattended: bool = True

    @property
    def key(self) -> tuple[str, str]:
        return self.official_patch_sha256, self.farmer_hash

    @classmethod
    def decode(cls, raw: bytes) -> "_Transaction":
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        stage = _Stage(data["stage"])
        reason = FailureReason(data["reason"]) if data["reason"] is not None else None
        log_path = data["log_path"]
        unattended = data.get("unattended", True)
        if (not all(isinstance(data[name], str) for name in ("official_patch_sha256", "farmer_hash", "detail"))
                or type(unattended) is not bool
                or (log_path is not None and not isinstance(log_path, str))
                or (stage in {_Stage.RESTORE, _Stage.BLOCKED}) != (reason is not None)):
            raise ValueError("invalid update transaction")
        return cls(data["official_patch_sha256"], data["farmer_hash"], GameUpdateState(data["classification"]),
                   stage, reason, data["detail"], log_path, unattended)


class GameUpdatePipeline:
    """One per service/profile, called by the service under its instance lock."""

    def __init__(
        self, os_: Platform, profile: Path, events: PipelineEvents, *,
        close_grace_seconds: float = GAME_CLOSE_GRACE_SECONDS,
        sources: Path | None = None, gdre: Gdre | None = None,
    ) -> None:
        self.os = os_
        self.profile = profile
        self.events = events
        self.sources = sources
        self.gdre = gdre
        self._grace = close_grace_seconds
        self._was_running = False
        self._closed_until = 0.0
        self._reinstall_reported = False
        self._journal = os_.app_data_dir() / "game-update.json"
        self._official_digest: tuple[tuple[Path, int, int, int, int, int], str] | None = None

    def run(self, *, check_again: bool = False, unattended: bool = True) -> PipelineResult:
        """Prepare once; call again on Wait. Invalid prerequisites raise PreflightError."""
        pending = self._load()
        if check_again and pending is not None and pending.reason is not None:
            pending = replace(pending, stage=_Stage.BUILD, reason=None, detail="", log_path=None, unattended=False)
            self._save(pending)
        if self.os.game_running():
            return self._busy()
        now = time.monotonic()
        if self._was_running:
            self._closed_until = now + self._grace
            self._was_running = False
        if now < self._closed_until:
            return self._wait(WAITING_FOR_GAME)

        mounted = _inspect(self.os, self.profile)
        if mounted is None:
            self.events.state("farmer_unavailable", START_GAME_AND_UPDATE)
            if not self._reinstall_reported:
                self.events.history({
                    "kind": "game_update", "classification": "game_reinstall",
                    "outcome": "blocked", "reason": START_GAME_AND_UPDATE,
                })
                self._reinstall_reported = True
            return Blocked(START_GAME_AND_UPDATE)
        self._reinstall_reported = False

        fingerprint = _farmer_hash(self.sources)
        classification = mounted.classify(fingerprint)
        if pending is None and classification is GameUpdateState.CURRENT:
            return self._ready()

        key = self._patch_hash(mounted.official), fingerprint
        interrupted = pending is not None
        if pending is not None and pending.key != key:
            pending = None
        if pending is not None and pending.reason is not None:
            if pending.stage is _Stage.BLOCKED:
                self.events.state("farmer_unavailable", pending.reason)
                return Blocked(pending.reason, pending.detail, Path(pending.log_path) if pending.log_path else None)
            return self._restore_and_quarantine(pending, mounted.mounted)

        try:
            game = self.os.game_executable()
        except RuntimeError as exc:
            raise PreflightError(str(exc)) from exc
        if not game.is_file() or not os.access(game, os.X_OK):
            raise PreflightError(f"game not found or not executable at {game}")

        info = mounted.info
        candidate = patch_info.built_pack_path(self.os)
        has_candidate = (
            mounted.same_base and info is not None and (info.patch_sha256, info.farmer_hash) == key
            and candidate.is_file()
        )
        if not mounted.mounted and info is not None and info.patch_sha256 != key[0]:
            classification = GameUpdateState.GAME_UPDATE
        if pending is None:
            # An interrupted build may already have published a candidate for the new key without smoking it.
            stage = _Stage.BUILD
            if not interrupted and has_candidate and info is not None:
                try:
                    if sha256(candidate) == info.result_sha256:
                        stage = _Stage.INSTALL
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    raise PreflightError(f"cannot read built farmer patch {candidate}: {exc}") from exc
            pending = _Transaction(*key, classification, stage, unattended=unattended)
            self._save(pending)
        elif not has_candidate and pending.stage is not _Stage.BUILD:
            pending = replace(pending, stage=_Stage.BUILD)
            self._save(pending)
        return self._prepare(pending, mounted, unattended)

    def _prepare(self, pending: _Transaction, mounted: _MountedPatch, unattended: bool) -> PipelineResult:
        try:
            if pending.stage is _Stage.BUILD:
                if not mounted.mounted:
                    self.events.state("rebuilding", "refreshing official state")
                    farmer_patch.snapshot_official_state(self.os, self.profile)
                self.events.state("rebuilding", "building farmer patch")
                info = farmer_patch.build(self.os, self.profile, sources=self.sources, gdre=self.gdre)
                if (info.patch_sha256, info.farmer_hash) != pending.key:
                    return self._wait("patch inputs changed; checking again")
                pending = replace(pending, stage=_Stage.SMOKE)
                self._save(pending)
            if pending.stage is _Stage.SMOKE:
                self.events.state("rebuilding", "running smoke in the sandbox")
                verdict = smoke.run_smoke(self.os, self.profile)
                if verdict.outcome is smoke.SmokeOutcome.BUSY:
                    return self._busy()
                if verdict.outcome is smoke.SmokeOutcome.FAILED:
                    return self._fail(pending, mounted.mounted, FailureReason.SMOKE_FAILED,
                                      verdict.reason, verdict.log_path)
                pending = replace(pending, stage=_Stage.INSTALL)
                self._save(pending)
            self.events.state("rebuilding", "installing farmer patch")
            farmer_patch.install(self.os, self.profile)
        except farmer_patch.GameRunning:
            return self._busy()
        except farmer_patch.AnchorsBroken as exc:
            return self._fail(pending, mounted.mounted, FailureReason.ANCHORS_BROKEN, str(exc), exc.log_path)
        except farmer_patch.BuildFailed as exc:
            return self._fail(pending, mounted.mounted, FailureReason.BUILD_FAILED, str(exc), exc.log_path)
        except farmer_patch.InstallFailed as exc:
            return self._fail(pending, mounted.mounted, FailureReason.BUILD_FAILED, f"install: {exc}", None)
        except (farmer_patch.PatchStateError, OSError) as exc:
            raise PreflightError(str(exc)) from exc

        self._journal.unlink()
        self._history(pending, "ready")
        if pending.classification is GameUpdateState.GAME_UPDATE and pending.unattended and unattended:
            self.events.notify("game_update_handled", "Game update handled; the farmer patch is ready")
        return self._ready()

    def _fail(
        self, pending: _Transaction, mounted: bool, reason: FailureReason, detail: str, log_path: Path | None,
    ) -> PipelineResult:
        pending = replace(pending, stage=_Stage.RESTORE, reason=reason, detail=" ".join(detail.splitlines()) or reason,
                          log_path=str(log_path) if log_path is not None else None)
        self._save(pending)
        return self._restore_and_quarantine(pending, mounted)

    def _restore_and_quarantine(self, pending: _Transaction, mounted: bool) -> PipelineResult:
        if mounted:
            try:
                # A failed Farmer-hash rebuild must not leave even the previous farmer patch mounted.
                farmer_patch.restore(self.os, self.profile)
            except farmer_patch.GameRunning:
                return self._busy()
            except (farmer_patch.PatchStateError, OSError) as exc:
                pending = replace(pending, detail=f"{pending.detail}; could not restore official patch: {exc}")
        reason = pending.reason
        assert reason is not None
        self._save(replace(pending, stage=_Stage.BLOCKED))
        fields: dict[str, str] = {"reason": reason, "detail": pending.detail}
        if pending.log_path is not None:
            fields["log_path"] = pending.log_path
        self._history(pending, "quarantine", **fields)
        self.events.state("farmer_unavailable", reason)
        self.events.notify(reason, pending.detail)
        return Quarantine(reason, pending.detail, Path(pending.log_path) if pending.log_path is not None else None)

    def _history(self, pending: _Transaction, outcome: str, **fields: str) -> None:
        self.events.history({
            "kind": "game_update", "classification": pending.classification.value, "outcome": outcome,
            "official_patch_sha256": pending.official_patch_sha256, "farmer_hash": pending.farmer_hash, **fields,
        })

    def _load(self) -> _Transaction | None:
        try:
            return _Transaction.decode(_read_shared(self.os, self._journal))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PreflightError(f"cannot read {self._journal}: {exc}") from exc

    def _save(self, pending: _Transaction) -> None:
        try:
            self._journal.parent.mkdir(parents=True, exist_ok=True)
            self.os.write_atomic(self._journal, json.dumps(asdict(pending)).encode())
        except OSError as exc:
            raise PreflightError(f"cannot write {self._journal}: {exc}") from exc

    def _patch_hash(self, path: Path) -> str:
        try:
            st = path.stat()
            stamp = (path, st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            if self._official_digest is None or self._official_digest[0] != stamp:
                self._official_digest = (stamp, sha256(path))
            return self._official_digest[1]
        except OSError as exc:
            raise PreflightError(f"cannot read official patch {path}: {exc}") from exc

    def _ready(self) -> Ready:
        self.events.state("ready", None)
        return Ready()

    def _wait(self, reason: str) -> Wait:
        self.events.state("waiting_for_game", reason)
        return Wait(reason)

    def _busy(self) -> Wait:
        self._was_running = True
        return self._wait(WAITING_FOR_GAME)
