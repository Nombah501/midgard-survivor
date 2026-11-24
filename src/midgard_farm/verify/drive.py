"""Drive the same launcher and supervisor that run normal AFK sessions."""

import json
import os
import shutil
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from dataclasses import dataclass, replace
from itertools import chain
from pathlib import Path
from threading import Event
from typing import TextIO

from ..platform import NetworkIsolationError, Platform
from ..core.commands import MAINTENANCE_CONFIG_KEYS, Character, Resume, SessionSettings, Start, submit
from ..core.launch import AttemptExit, GameBusy, run_attempt
from ..core.preflight import PreflightError
from ..core.state import StateKind, StateReporter, read_state
from ..core.supervisor import Policy, Supervisor, session_log_dir


@dataclass(frozen=True)
class Run:
    os: Platform
    profile: Path
    work: Path
    out: Path
    name: str
    session: str
    stop: Callable[[], float | None]
    policy: Policy
    soak_hours: float = 0.0

    def artifact(self, suffix: str) -> Path:
        return self.out / f"{self.name}.{suffix}"

    def status(self) -> dict:
        try:
            status = json.loads(self.os.read_shared(self.profile / "farmer_status.json"))
        except (OSError, ValueError):
            return {}
        return status if isinstance(status, dict) else {}


@dataclass(frozen=True)
class Driven:
    code: int
    outputs: tuple[Path, ...]
    failure: str = ""
    crash_code: int | None = None
    killed_r1: bool = False
    outcome: dict | None = None


@contextmanager
def _sandbox_launch_environment(**enabled: str) -> Iterator[None]:
    # The core launcher uses this worker's environment. Never inherit a
    # backup path (rotation writes/deletes there), display override or hook.
    old = {k: v for k, v in os.environ.items()
           if k.startswith("FARMER_TEST_") or k in {"FARMER_BACKUP_DIR", "FARMER_DISPLAY"}}
    keys = old.keys() | enabled.keys()
    try:
        for key in keys:
            os.environ.pop(key, None)
        os.environ.update(enabled)
        yield
    finally:
        for key in keys:
            os.environ.pop(key, None)
        os.environ.update(old)


def _exit_code(result: AttemptExit, os_: Platform) -> int:
    if result.forced_reason == "timeout":
        return 124
    if result.forced_reason == "interrupted":
        return 130
    if result.clean(os_):
        return 0
    # As in the service CLI/run.sh, a terminal failure's own code is authoritative.
    status = result.status or {}
    code = status.get("exit_code")
    if type(code) is int and 0 < code <= 255:
        return code
    return result.normalized_code or 1


def direct(run: Run, timeout: float, *, output: str = "run.log", command: bool = False,
           **hooks: str) -> Driven:
    deadline = time.monotonic() + timeout
    log = run.artifact(output)
    log.touch()
    driver = _CommandDriver(run) if command else None

    def watch(status: dict | None) -> str | None:
        if run.stop() is not None:
            return "interrupted"
        if time.monotonic() >= deadline:
            return "timeout"
        return driver.observe(status or {}) if driver else None

    try:
        run.os.write_atomic(run.profile / "farmer.cfg", run.artifact("json").read_bytes())
        with _sandbox_launch_environment(**hooks):
            result = run_attempt(run.os, run.profile, None, run.session, log_path=log,
                                 watch=watch, poll_interval=0.01 if driver else 0.05)
    except (PreflightError, NetworkIsolationError) as exc:
        return Driven(78, (log,), str(exc))
    except (GameBusy, OSError) as exc:
        return Driven(1, (log,), str(exc))
    if result.forced_reason == "timeout":
        failure = f"game timed out after {timeout:g} s"
    else:
        failure = result.forced_reason or (driver.unobserved() if driver else "")
    return Driven(_exit_code(result, run.os), (log,), failure)


class _CommandDriver:
    def __init__(self, run: Run):
        self.run = run
        self.expected = "run"
        self.run_id = self.pid = self.heartbeat = None
        self.deadline = time.monotonic() + 30
        self.complete = False

    def unobserved(self) -> str:
        return "" if self.complete else f"expected phase {self.expected!r} was not observed"

    def _publish(self, command: str) -> None:
        self.run.os.write_atomic(self.run.profile / "farmer_command", f"{command}\n".encode())

    def _expect(self, phase: str) -> None:
        self.expected, self.deadline = phase, time.monotonic() + 30

    def observe(self, status: dict) -> str | None:
        if self.complete:
            return None
        if time.monotonic() >= self.deadline or status.get("terminal"):
            return self.unobserved()
        phase = status.get("phase")
        name = self.run.name
        if self.expected == "keep" and phase == "keep":
            if status.get("run_id") != self.run_id:
                return "settlement did not belong to the running run"
            self._publish("abort")
        elif self.expected == "paused" and phase == "paused":
            totals = status.get("totals") or {}
            if self.heartbeat is None:
                if totals.get("runs") != 1 or status.get("run_id") != self.run_id:
                    return "pause did not finish the running run"
                self.heartbeat = status.get("heartbeat_seq")
                self._expect("paused")
            elif status["heartbeat_seq"] > self.heartbeat:
                if totals.get("started") != 1:
                    return "paused farmer started another run"
                if status.get("pid") != self.pid:
                    return "paused farmer changed pid"
                self._publish("resume")
                self._expect("resumed run")
            return None
        elif self.expected == "resumed run" and phase == "run" and status.get("run_id") != self.run_id:
            if status.get("pid") != self.pid:
                return "resume did not continue in the same pid"
        elif self.expected == "run" and phase == "run":
            self.run_id, self.pid = status.get("run_id"), status.get("pid")
            if name == "cmd-abort-settled":
                self._expect("keep")
                return None
            if name == "cmd-pause-resume":
                self._publish("pause")
                self._expect("paused")
                return None
            if name == "cmd-legacy":
                (self.run.profile / "farmer_stop").touch()
            else:
                self._publish(name.removeprefix("cmd-"))
        else:
            return None
        self.complete = True
        return None


def crash(run: Run, timeout: float, point: str) -> Driven:
    first = direct(run, timeout, output="crash.log", FARMER_TEST_CRASH_AT=point)
    boot = run.profile / "farmer.log"
    if boot.is_file():
        shutil.copyfile(boot, run.artifact("crash.farmer.log"))
    if first.failure:
        return first
    second = direct(run, timeout)
    return replace(second, outputs=first.outputs + second.outputs, crash_code=first.code)


def corrupt_checkpoint(run: Run, timeout: float) -> Driven:
    (run.profile / "farmer_session.json").write_text(f'{{"session":"{run.session}","phase":"sett', encoding="utf-8")
    return direct(run, timeout)


def _disk_kb(os_: Platform, *roots: Path) -> int:
    size = 0
    for root in roots:
        for path in chain((root,), root.rglob("*")):
            try:
                if path.is_file() and not path.is_symlink():
                    size += os_.allocated_bytes(path)
            except OSError:  # A log, backup or status may have just been replaced.
                continue
    return size // 1024


def _sample(run: Run, stream: TextIO) -> None:
    status = run.status()
    pid = status.get("pid")
    rss = run.os.process_rss_kib(pid) if type(pid) is int and pid > 0 else None
    print(json.dumps({"t": time.time(), "heartbeat_seq": status.get("heartbeat_seq"),
                      "phase": status.get("phase"), "pid": pid, "rss_kb": rss,
                      "disk_kb": _disk_kb(run.os, run.work, run.artifact("run.log"))}), file=stream, flush=True)


@contextmanager
def _sample_during(run: Run) -> Iterator[None]:
    # Keep sampling through launcher preflight, restarts and backup I/O.
    with run.artifact("samples.jsonl").open("w", encoding="utf-8") as samples, ThreadPoolExecutor(1) as pool:
        done = Event()
        _sample(run, samples)

        def tick() -> None:
            while not done.wait(5):
                _sample(run, samples)

        task = pool.submit(tick)
        try:
            yield
        finally:
            done.set()
            task.result()
            _sample(run, samples)


def supervised(run: Run, timeout: float, *, kill_run: bool = False, crash_at: str = "",
               sample: bool = False, resume: SessionSettings | None = None, resume_after_runs: int = 0,
               **hooks: str) -> Driven:
    app_data = run.os.app_data_dir()
    log_dir = session_log_dir(run.os, run.session)
    outcome_path = log_dir / "outcome.json"
    session_path = app_data / "session.json"
    main_log = run.artifact("run.log")
    deadline = time.monotonic() + timeout
    killed, stop_at, forced = False, None, 0
    if crash_at:
        hooks["FARMER_TEST_CRASH_AT"] = crash_at
    config = json.loads(run.artifact("json").read_bytes())
    # Session keys go to Start; the sandbox-only strategy stays outside the command protocol.
    cid = config.pop("class", None)
    danger = config.pop("danger", "auto")
    switches = {}
    defaults = SessionSettings().maintenance()
    for name, keys in MAINTENANCE_CONFIG_KEYS.items():
        enabled, *paired = (config.pop(key, defaults[name]) for key in keys)
        if any(value != enabled for value in paired):
            raise ValueError(f"verify config disagrees on the {name} switch")
        switches[name] = enabled
    settings = SessionSettings(config.pop("stage", None) or None, None if danger == "auto" else danger,
                               config.pop("oaths", {}), config.pop("wishlist", []),
                               show_game_window=config.pop("display", False),
                               keep_unowned_legendaries=config.pop("keep_unowned_legendaries", False),
                               experimental_speed=config.pop("experimental_speed", False),
                               mode="endless" if config.get("endless") else "short", **switches)
    strategy = run.artifact("strategy.json")
    strategy.write_text(json.dumps(config, indent=2), encoding="utf-8")
    character = Character(cid, config.get("job_paths", {}).get(cid, 0)) if cid is not None else None
    start = Start(character, settings)
    pause_sent = resume_sent = False

    with (run.os.acquire_lock(app_data / "service.lock"),
          run.os.acquire_lock(run.profile / "farmer_supervisor.lock"),
          StateReporter(run.os) as state,
          main_log.open("w", encoding="utf-8") as log,
          redirect_stdout(log), redirect_stderr(log), _sandbox_launch_environment(**hooks),
          _sample_during(run) if sample else nullcontext()):
        run.os.write_atomic(session_path, json.dumps({"id": run.session, "start": start.payload(),
                                                      "profile": str(run.profile), "request": "verify.json"}).encode())

        def stop_requested_at() -> float | None:
            nonlocal killed, stop_at, forced, pause_sent, resume_sent
            if stop_at is not None:
                return stop_at
            now = time.monotonic()
            if now >= deadline:
                stop_at, forced = now, 124
            elif run.stop() is not None:
                stop_at, forced = now, 130
            elif outcome_path.is_file() and not session_path.exists():
                stop_at = now  # A published outcome ends this verification, not the service by itself.
            elif kill_run and not killed:
                status = run.status()
                pid = status.get("pid")
                if (status.get("phase") == "run" and status.get("session") == run.session
                        and status.get("run_id") == f"{run.session}-r1" and type(pid) is int
                        and run.os.kill_owned_sandbox_game(pid, run.work, run.session)):
                    killed = True
                    print(f"drive: SIGKILL game pid {pid} in run {status['run_id']}", flush=True)
            elif resume is not None and not resume_sent:
                state = read_state(run.os)
                if state.kind is StateKind.ACTIVE and state.session_id == run.session:
                    if (state.farmer_phase == "run" and not pause_sent
                            and (not resume_after_runs or run.status().get("totals", {}).get("runs", 0)
                                 >= resume_after_runs)):
                        submit(run.os, "pause")
                        pause_sent = True
                    elif state.farmer_phase == "paused" and pause_sent:
                        submit(run.os, Resume(resume))
                        resume_sent = True
            return stop_at

        policy = replace(run.policy, stop_grace=120 if sample else 30)
        Supervisor(run.os, run.profile, policy, stop_requested_at, lambda *_: None,
                   state=state, session_prefix="verify", strategy=strategy).run()

    logs = run.artifact("supervisor") / log_dir.name
    outcome: dict = {}
    if log_dir.is_dir():
        shutil.copytree(log_dir, logs)
        if outcome_path.is_file():
            outcome = json.loads(outcome_path.read_bytes())
    boot = run.profile / "farmer.log.prev"
    if boot.is_file():
        shutil.copyfile(boot, run.artifact("crash.farmer.log"))
    outputs = (main_log, *sorted(logs.glob("attempt-*.log")))
    if forced == 124:
        return Driven(124, outputs, "soak overran max_minutes by more than 30 min" if sample
                      else f"supervised scenario timed out after {timeout:g} s")
    if forced == 130:
        return Driven(130, outputs, "interrupted")
    code = 2 if outcome.get("kind") == "quarantined" else 0 if outcome else 1
    return Driven(code, outputs, killed_r1=killed, outcome=outcome)
