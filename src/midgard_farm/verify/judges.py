"""Verify captured game evidence, not just process exit codes."""

import json
import re
from collections import Counter
from pathlib import Path

from ..core import smoke
from .drive import Driven, Run
from .soak import judge_files, read_jsonl


class VerificationFailure(Exception):
    pass


def need(condition: object, message: str) -> None:
    if not condition:
        raise VerificationFailure(message)


def _marker(run: Run, marker: str) -> None:
    path = run.artifact("farmer.log")
    need(path.is_file(), "no farmer.log")
    need(marker in path.read_text(encoding="utf-8"), f"missing log marker: {marker}")


def _done(status: dict, *, needs_run: bool = True) -> None:
    need(status.get("phase") == "done", "phase != done")
    need(status.get("terminal"), "terminal false")
    need(not status.get("failed"), "failed true")
    need(status.get("finish_reason"), "finish_reason empty")
    need(status.get("last_transition"), "last_transition empty")
    need(int(status.get("heartbeat_seq") or 0) > 0, "heartbeat_seq == 0")
    need(status.get("run_id"), "run_id empty")
    if needs_run:
        need(int((status.get("totals") or {}).get("runs") or 0) >= 1, "runs == 0")


def _exit(driven: Driven, code: int = 0) -> None:
    need(driven.code == code, f"launch exit {driven.code} (expected {code})")


def one_run(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    reason = smoke.judge_one_run(run.os, run.profile, driven.outputs[0])
    need(not reason, reason)


def stop(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    last = status.get("last") or {}
    need(last, "no last run")
    need(int(last.get("kills") or 0) > 0, "kills == 0")
    need(float(last.get("game_s") or 0) > 0, "game_s == 0")
    _marker(run, "STOP max_minutes")


def endless(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    last = status.get("last") or {}
    need(last.get("victory"), "last.victory false")
    need(last.get("endless"), "last.endless false")
    need(int(last.get("endless_mvps") or 0) >= 1, "endless_mvps == 0")
    need(int(last.get("kills") or 0) > 0, "kills == 0")
    _marker(run, "ENDLESS_DONE")


def run_stall(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    _done(status)
    _marker(run, "RUN_STALL")
    _marker(run, "tries=3")
    need((status.get("last") or {}).get("forced"), "frozen run was not forced")


def failed(run: Run, driven: Driven, status: dict, reason: str) -> None:
    _exit(driven, 1)
    need(status.get("phase") == "failed", "phase != failed")
    need(status.get("terminal"), "terminal false")
    need(status.get("failed"), "failed false")
    need(status.get("finish_reason") == reason, f"finish_reason != {reason}")
    need(int(status.get("exit_code") or 0) != 0, "exit_code == 0")
    need(status.get("last_transition"), "last_transition empty")
    _marker(run, f"FAIL {reason}")


def checkpoint_corrupt(run: Run, driven: Driven, status: dict) -> None:
    failed(run, driven, status, "checkpoint_corrupt")
    snapshot, = (run.work / "install-backups").glob("install-*/profile.json")
    need((run.profile / "profile.json").read_bytes() == snapshot.read_bytes(),
         "profile changed although the session could not start")


def _journal(path: Path) -> list[dict]:
    return read_jsonl(path) if path.is_file() else []


def command(run: Run, driven: Driven, status: dict) -> None:
    _exit(driven)
    name = run.name
    _done(status, needs_run=name != "cmd-abort")
    _marker(run, "FINISH")
    log = run.artifact("farmer.log").read_text(encoding="utf-8")
    checkpoint = json.loads(run.artifact("checkpoint.json").read_bytes())
    session, totals = status["session"], status["totals"]
    rows = [row for row in _journal(run.artifact("journal.jsonl")) if row["session"] == session]
    abort, paused = name.startswith("cmd-abort"), name == "cmd-pause-resume"
    started = 2 if paused else 1
    lost = int(name == "cmd-abort")
    runs = started - lost
    reason = "abort" if abort else "max_runs" if paused else "finish"
    need(status.get("finish_reason") == reason, f"finish_reason != {reason}")
    need(status.get("exit_code") == 0, "exit_code != 0")
    need(checkpoint.get("phase") == "idle" and checkpoint.get("session") == session,
         "checkpoint is not idle in the same session")
    need(checkpoint.get("totals") == totals, "checkpoint totals differ from status")
    need((totals.get("started"), totals.get("runs"), totals.get("lost")) == (started, runs, lost),
         f"expected {started} started, {runs} settled and {lost} lost")
    need([r["run_id"] for r in rows] == [f"{session}-r{i}" for i in range(1, runs + 1)], "wrong journal run IDs")
    need(totals.get("zeny") == sum(r["zeny_gain"] for r in rows), "totals.zeny != journal zeny_gain sum")
    need(not any((run.profile / f).exists() for f in ("farmer_command", "farmer_command.claimed", "farmer_stop")),
         "unconsumed farmer command")
    need(log.count(" SETTLE ") == runs, f"expected {runs} SETTLE markers")
    if abort:
        need(" KEEP_DONE " not in log and " MAINT " not in log, "abort performed keep or maintenance")
        need(all(not r["kept"] for r in rows), "abort kept an item")
    else:
        need(log.count(" KEEP_DONE ") == log.count(" MAINT ") == started,
             f"expected {started} KEEP_DONE and MAINT markers")
        force = "run_timeout" if paused else "finish"
        need(all(r["force_reason"] == force for r in rows), f"journal force_reason != {force}")


def recovered(run: Run, driven: Driven, status: dict, point: str, marker: str, *, supervised: bool = False) -> None:
    _exit(driven)
    boot_path = run.artifact("crash.farmer.log")
    need(boot_path.is_file(), "no attempt-1 farmer.log")
    boot_log = boot_path.read_text(encoding="utf-8")
    if supervised:
        outcome = driven.outcome or {}
        attempts = outcome.get("attempts") or []
        number_and_outcome = [(a.get("number"), a.get("outcome")) for a in attempts]
        need(number_and_outcome == [(1, "failed"), (2, "finished")],
             "supervisor did not fail attempt 1 and finish attempt 2")
    else:
        need(driven.crash_code not in (None, 0, 124), f"crash launch exit {driven.crash_code} (expected killed farmer)")
    if supervised and point == "run":
        need(driven.killed_r1, "the game was not killed in run r1")
    else:
        need(f"TEST_CRASH {point}" in boot_log, f"crash launch did not reach {point}")
    need(status.get("phase") == "done" and not status.get("failed"), "phase != done")
    need(status.get("session") == run.session, "session id not continued")
    totals = status.get("totals") or {}
    journal = run.artifact("journal.jsonl")
    need(journal.is_file(), "no farmer_runs.jsonl")
    rows = [row for row in _journal(journal) if row.get("session") == run.session]
    ids = Counter(row.get("run_id") for row in rows)
    need(all(count == 1 for count in ids.values()), f"duplicate journal run_id: {dict(ids)}")
    need(int(totals.get("runs") or 0) == len(rows), f"totals.runs {totals.get('runs')} != journal {len(rows)}")
    zeny = int(totals.get("zeny") or 0)
    need(zeny == sum(int(row.get("zeny_gain") or 0) for row in rows), "totals.zeny != journal zeny_gain sum")
    need(int(totals.get("started") or 0) == 2, f"totals.started {totals.get('started')} != 2")
    boot = re.search(r" BOOT .* zeny=(\d+)", boot_log)
    if boot is None:
        raise VerificationFailure("no BOOT zeny in the crash launch log")
    moved = int((status.get("profile") or {}).get("zeny") or 0) - int(boot.group(1))
    need(moved == zeny, f"profile zeny moved {moved} != totals.zeny {zeny}")
    lost = int(point == "run")
    need(int(totals.get("lost") or 0) == lost, f"totals.lost {totals.get('lost')} != {lost}")
    need(set(ids) == {f"{run.session}-r{i}" for i in range(lost + 1, 3)}, f"wrong journal IDs: {list(ids)}")
    _marker(run, marker)


def soak(run: Run, driven: Driven, _status: dict) -> None:
    ok, problems, summary = judge_files(run.artifact("samples.jsonl"), run.artifact("journal.jsonl"),
                                        run.artifact("status.json"), session=run.session,
                                        supervisor_exit=driven.code, min_hours=run.soak_hours)
    lines = [json.dumps(summary), *(f"soak: FAIL {failure}" for failure in problems),
             "soak: PASS" if ok else "soak: FAIL"]
    path = run.artifact("verdict.log")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    need(ok, f"soak check failed (see {path.name})")
