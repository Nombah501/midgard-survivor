#!/usr/bin/env python3
"""AFK supervisor: start the farmer, watch it, restart or quarantine it.

  ./tools/supervisor.py [PRESET]              supervise ./run.sh [PRESET]
  ./tools/supervisor.py --print-unit [PRESET] print a user systemd unit

The supervisor owns the AFK terminal outcome (docs/adr/0003):

- clean finish (exit 0 and phase=done) ends the session; nothing restarts;
- a crash, a silent exit or a heartbeat older than three intervals is a
  failure: the whole process group is killed and the farmer restarts after
  an exponential backoff;
- max_failures failures inside failure_window, a fatal run.sh preflight
  (exit 78: missing game/patch, stale build, bad preset) or an invalid
  farmer config put the session in quarantine: no restart,
  diagnostics stay in the session log directory, the supervisor exits 2;
- SIGTERM/SIGINT stop the supervisor: the farmer's process group gets
  SIGTERM, then SIGKILL after kill_grace.

Notifications go to notify-send and, when FARMER_NTFY_URL (or --ntfy-url) is
set, to ntfy. They run in background threads; a failed notification never
delays recovery.

Exit codes: 0 finished or stopped by the operator, 2 quarantine, 1 supervisor
error. systemd restarts only the last one (RestartPreventExitStatus=2).
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

FARMER_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = (
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    / "godot/app_userdata/Midgard Survivors"
)
EXIT_PREFLIGHT = 78  # run.sh EX_CONFIG: missing game/patch, stale build, bad preset
# Farmer terminal reasons a restart cannot fix.
FATAL_REASONS = {"cfg_invalid", "checkpoint_corrupt"}
# Present only while a session has no terminal outcome: a supervisor that
# systemd restarts after its own crash continues the same AFK session.
SESSION_FILE = DATA_DIR / "farmer_supervisor_session"
EXIT_QUARANTINE = 2


@dataclass(frozen=True)
class Policy:
    heartbeat_interval: float = 5.0  # farmer STATUS_EVERY_MS
    stale_intervals: int = 3
    startup_grace: float = 180.0  # until the first heartbeat after a spawn
    backoff_base: float = 15.0
    backoff_max: float = 600.0
    max_failures: int = 4
    failure_window: float = 3600.0
    kill_grace: float = 20.0  # SIGTERM -> SIGKILL; also exit wait after a terminal status


@dataclass
class Attempt:
    number: int
    delay: float  # backoff slept before this attempt
    outcome: str  # finished | failed | fatal | stopped
    reason: str
    exit_code: int | None


@dataclass
class TerminalOutcome:
    """How the AFK session ended (GLOSSARY: Terminal outcome)."""

    kind: str  # finished | quarantined | stopped
    reason: str
    attempts: list[Attempt] = field(default_factory=list)
    log_dir: Path | None = None


def log(message):
    print(f"supervisor: {message}", flush=True)


def read_status(path, since_ns):
    """The farmer status, if it was written after since_ns (wall clock)."""
    try:
        path = Path(path)
        if path.stat().st_mtime_ns < since_ns:
            return None  # a previous attempt's or another launcher's status
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class Supervisor:
    def __init__(self, command, status_path, log_dir, policy=Policy(), notify=None):
        self.command = list(command)
        self.status_path = Path(status_path)
        self.log_dir = Path(log_dir)
        self.policy = policy
        self.notify = notify or (lambda event, message: None)
        self._stopping = False  # a plain flag: request_stop runs in a signal handler

    def request_stop(self):
        self._stopping = True

    def run(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        outcome = TerminalOutcome("stopped", "operator", log_dir=self.log_dir)
        failures = deque()
        delay = 0.0
        while True:
            if delay:
                log(f"restart in {delay:.1f}s")
                self._sleep(delay)
            if self._stopping:
                return self._stopped(outcome)
            attempt = self._attempt(len(outcome.attempts) + 1, delay)
            outcome.attempts.append(attempt)
            if attempt.outcome == "stopped":
                return self._stopped(outcome)
            if attempt.outcome == "finished":
                outcome.kind, outcome.reason = "finished", attempt.reason
                event = "goal" if attempt.reason == "goal" else "stop"
                self.notify(event, f"farmer finished: {attempt.reason}")
                return outcome
            if attempt.outcome == "fatal":
                return self._quarantine(outcome, attempt.reason)
            now = time.monotonic()
            failures.append(now)
            while failures and now - failures[0] > self.policy.failure_window:
                failures.popleft()
            if len(failures) >= self.policy.max_failures:
                return self._quarantine(
                    outcome, f"{len(failures)} failures in {self.policy.failure_window:.0f}s"
                )
            self.notify("fail", f"farmer failed: {attempt.reason}; restarting")
            delay = min(
                self.policy.backoff_max,
                self.policy.backoff_base * 2 ** (len(failures) - 1),
            )

    def _sleep(self, seconds):
        deadline = time.monotonic() + seconds
        while not self._stopping and (left := deadline - time.monotonic()) > 0:
            time.sleep(min(left, 0.2))

    def _stopped(self, outcome):
        log("stopped by operator")
        self.notify("stop", "supervisor stopped by operator")
        return outcome

    def _quarantine(self, outcome, reason):
        outcome.kind, outcome.reason = "quarantined", reason
        last = outcome.attempts[-1]
        (self.log_dir / "quarantine.json").write_text(
            json.dumps(
                {
                    "reason": reason,
                    "last_failure": last.reason,
                    "attempts": [a.__dict__ for a in outcome.attempts],
                },
                indent=2,
            )
        )
        log(f"QUARANTINE {reason}; diagnostics in {self.log_dir}")
        self.notify("quarantine", f"farmer quarantined: {reason} (last: {last.reason})")
        return outcome

    def _attempt(self, number, delay):
        stem = self.log_dir / f"attempt-{number:02d}"
        log(f"attempt {number}: {' '.join(self.command)}")
        since_ns = time.time_ns()
        with open(f"{stem}.log", "wb") as out:
            proc = subprocess.Popen(
                self.command, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
            )
            code, status, reason = self._watch(proc, since_ns)
        if reason == "operator":
            outcome = "stopped"
        elif reason is None:
            outcome, reason = self._classify(code, status)
        else:
            outcome = "failed"
        if outcome != "finished" and status is not None:
            Path(f"{stem}.status.json").write_text(json.dumps(status, indent=2))
        log(f"attempt {number}: {outcome} ({reason}, exit {code})")
        return Attempt(number, delay, outcome, reason, code)

    def _watch(self, proc, since_ns):
        """Wait for the child; return (exit_code, last_status, forced_reason).

        The child stays unreaped (a zombie) until its group has been killed,
        so the group id cannot be recycled under killpg.
        """
        p = self.policy
        stale = p.heartbeat_interval * p.stale_intervals
        tick = max(0.05, p.heartbeat_interval / 5)
        last_seq, last_change, status = None, time.monotonic(), None
        while True:
            if self._exited(proc):
                status = read_status(self.status_path, since_ns) or status
                self._kill_group(proc, signal.SIGKILL)  # leftovers of a dead child
                return proc.wait(), status, None
            if self._stopping:
                self._terminate(proc)
                return proc.returncode, read_status(self.status_path, since_ns) or status, "operator"
            current = read_status(self.status_path, since_ns)
            now = time.monotonic()
            if current is not None:
                status = current
                seq = current.get("heartbeat_seq")
                if seq != last_seq:
                    last_seq, last_change = seq, now
            if status is not None and status.get("terminal"):
                limit, reason = p.kill_grace, "no_exit_after_terminal"
            elif last_seq is None:
                limit, reason = p.startup_grace, "no_heartbeat"
            else:
                limit, reason = stale, "heartbeat_stale"
            if now - last_change > limit and not self._exited(proc):
                log(f"{reason}: {now - last_change:.1f}s without a heartbeat")
                self._kill_group(proc, signal.SIGKILL)  # a hung farmer cannot flush (ADR 0001)
                return proc.wait(), status, reason
            time.sleep(tick)

    def _classify(self, code, status):
        status = status or {}
        reason = str(status.get("finish_reason") or "")
        if code == 0 and status.get("phase") == "done" and not status.get("failed"):
            return "finished", reason or "done"
        if code == EXIT_PREFLIGHT:
            return "fatal", "preflight_failed"
        if reason in FATAL_REASONS:
            return "fatal", reason
        if status.get("failed") and reason:
            return "failed", reason
        if not status:
            return "failed", f"exit_{code}_no_status"
        return "failed", f"exit_{code}_phase_{status.get('phase', '')}"

    def _terminate(self, proc):
        self._kill_group(proc, signal.SIGTERM)
        deadline = time.monotonic() + self.policy.kill_grace
        while not self._exited(proc) and time.monotonic() < deadline:
            time.sleep(0.1)
        self._kill_group(proc, signal.SIGKILL)
        proc.wait()

    @staticmethod
    def _exited(proc):
        """True once the child has exited; does not reap it."""
        if proc.returncode is not None:
            return True
        return os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None

    @staticmethod
    def _kill_group(proc, sig):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass


def make_notifier(ntfy_url):
    def send(title, message):
        if shutil.which("notify-send"):
            try:
                subprocess.run(
                    ["notify-send", "-a", "Midgard farmer", title, message],
                    timeout=10, check=False, capture_output=True,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                log(f"notify-send failed: {exc}")
        if ntfy_url:
            request = urllib.request.Request(
                ntfy_url, data=message.encode(), headers={"Title": title}
            )
            try:
                urllib.request.urlopen(request, timeout=10).close()
            except OSError as exc:
                log(f"ntfy failed: {exc}")

    pending = []

    def notify(event, message):
        log(f"notify {event}: {message}")
        thread = threading.Thread(
            target=send, args=(f"Midgard farmer: {event}", message), daemon=True
        )
        thread.start()
        pending.append(thread)

    def drain(timeout):
        """Give in-flight notifications up to timeout seconds before exit."""
        deadline = time.monotonic() + timeout
        for thread in pending:
            thread.join(max(0.0, deadline - time.monotonic()))

    notify.drain = drain
    return notify


UNIT = """\
# Midgard Survivors AFK supervisor. Generated by: {script} --print-unit
#   {script} --print-unit [PRESET] > ~/.config/systemd/user/midgard-farmer.service
#   systemctl --user daemon-reload && systemctl --user start midgard-farmer
#
# systemd only keeps the supervisor alive; restart/backoff/quarantine policy
# for the farmer lives in the supervisor (docs/adr/0003).
# - exit 0 (finished/stopped): not restarted;
# - exit 2 (quarantine): not restarted, inspect farmer/logs/supervisor-*;
# - any other failure of the supervisor itself: restarted after 30s,
#   at most 3 times per hour.
# Stop sends SIGTERM; the supervisor terminates the farmer's process group.
# KillMode=control-group also reaps anything left in the cgroup.
[Unit]
Description=Midgard Survivors AFK farmer supervisor
StartLimitIntervalSec=1h
StartLimitBurst=3

[Service]
Type=simple
ExecStart={exec_start}
# Optional: FARMER_NTFY_URL=https://ntfy.sh/<topic>
EnvironmentFile=-%h/.config/midgard-farmer.env
Restart=on-failure
RestartSec=30
RestartPreventExitStatus=2
KillMode=control-group
TimeoutStopSec=60

[Install]
WantedBy=default.target
"""


def systemd_quote(arg):
    """One ExecStart argument: double-quoted, specifiers and variables escaped."""
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped.replace("%", "%%").replace("$", "$$") + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("preset", nargs="?", help="preset passed to run.sh")
    parser.add_argument("--ntfy-url", default=os.environ.get("FARMER_NTFY_URL", ""))
    parser.add_argument("--print-unit", action="store_true", help="print a systemd user unit")
    args = parser.parse_args()
    preset = str(Path(args.preset).resolve()) if args.preset else None

    if args.print_unit:
        argv = [sys.executable, str(Path(__file__).resolve())] + ([preset] if preset else [])
        print(UNIT.format(
            script=Path(__file__).resolve(),
            exec_start=" ".join(systemd_quote(a) for a in argv),
        ), end="")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
    try:
        session = SESSION_FILE.read_text().strip()
    except OSError:
        session = ""
    if session:
        log(f"continuing unfinished session {session}")
    else:
        session = f"afk-{stamp}"
        SESSION_FILE.write_text(session)
    # One AFK session id for every restart: the farmer continues its checkpoint.
    os.environ["FARMER_SESSION_ID"] = session
    notify = make_notifier(args.ntfy_url)
    sup = Supervisor(
        command=[str(FARMER_DIR / "run.sh")] + ([preset] if preset else []),
        status_path=DATA_DIR / "farmer_status.json",
        log_dir=FARMER_DIR / "logs" / f"supervisor-{stamp}",
        notify=notify,
    )
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sup.request_stop())
    outcome = sup.run()
    SESSION_FILE.unlink(missing_ok=True)  # terminal outcome: the next start is a new session
    log(f"session {outcome.kind}: {outcome.reason} after {len(outcome.attempts)} attempt(s)")
    notify.drain(25)  # below TimeoutStopSec minus kill_grace
    if outcome.kind == "quarantined":
        return EXIT_QUARANTINE
    return 0


if __name__ == "__main__":
    sys.exit(main())
