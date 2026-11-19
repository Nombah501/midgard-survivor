#!/usr/bin/env python3
"""Verdict of an AFK soak: sampler log + run journal + final farmer status.

  ./tools/soak_check.py SAMPLES.jsonl JOURNAL.jsonl STATUS.json --session ID --supervisor-exit N [--min-hours H]

Prints one JSON summary line and every problem; exits 1 when the soak failed.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

MAX_HEARTBEAT_GAP_S = 15.0  # three 5 s status intervals: the supervisor's stale limit
WARMUP_S = 3600.0  # caches and pools fill during the first hour
MAX_RSS_GROWTH = 0.5  # after warmup
MAX_DISK_GROWTH_MIB = 200
# Status totals the journal reconstructs: total name -> one journal row's share.
JOURNAL_TOTALS = {
    "wins": lambda r: int(bool(r.get("victory"))),
    "losses": lambda r: int(not r.get("victory")),
    "zeny": lambda r: int(r.get("zeny_gain") or 0),
    "kills": lambda r: int(r.get("kills") or 0),
    "xp": lambda r: int(r.get("xp_gain") or 0),
    "coins": lambda r: int(r.get("coins_gain") or 0),
    "ymir": lambda r: int(r.get("ymir_gain") or 0),
}


def heartbeat_gap(samples):
    """Longest wall time without a new heartbeat after the first one; None if none seen.

    A missing status (game boot, a restart's cleanup) is no new heartbeat.
    """
    gap, last_t, last_seq = 0.0, None, None
    for s in samples:
        seq = s.get("heartbeat_seq")
        if seq is None or seq == last_seq:
            continue
        if last_t is not None:
            gap = max(gap, s["t"] - last_t)
        last_t, last_seq = s["t"], seq
    if last_t is None:
        return None
    return max(gap, samples[-1]["t"] - last_t)


def rss_after_warmup(samples):
    """(RSS at the end of warmup, max RSS after it) in MiB, or None when too short."""
    if not samples:
        return None
    t0 = samples[0]["t"]
    late = [s["rss_kb"] // 1024 for s in samples if s["t"] - t0 >= WARMUP_S and s.get("rss_kb")]
    return (late[0], max(late)) if late else None


def verdict(samples, journal, status, *, supervisor_exit, session, min_hours=0.0):
    """Return (ok, problems, summary) for one soak."""
    problems = []
    if supervisor_exit != 0:
        kind = " (quarantine)" if supervisor_exit == 2 else ""
        problems.append(f"supervisor exit {supervisor_exit}{kind}")
    if status.get("phase") != "done" or status.get("failed"):
        problems.append(f"farmer did not finish cleanly: {status.get('phase')}/{status.get('finish_reason')}")
    rows = [r for r in journal if r.get("session") == session]
    hours = (samples[-1]["t"] - samples[0]["t"]) / 3600 if samples else 0.0
    if hours < min_hours:
        problems.append(f"soak lasted {hours:.1f} h < {min_hours:.1f} h")
    zeny = sum(JOURNAL_TOTALS["zeny"](r) for r in rows)
    gap = heartbeat_gap(samples)
    if gap is None:
        problems.append("no heartbeat observed")
    elif gap > MAX_HEARTBEAT_GAP_S:
        problems.append(f"heartbeat gap {gap:.1f}s > {MAX_HEARTBEAT_GAP_S}s")
    rss = rss_after_warmup(samples)
    if rss is None:
        problems.append("no game RSS sample after the first hour")
    elif rss[1] > rss[0] * (1 + MAX_RSS_GROWTH):
        problems.append(f"game RSS grew {(rss[1] - rss[0]) * 100 // rss[0]}% after the first hour "
                        f"({rss[0]} -> {rss[1]} MiB) > {MAX_RSS_GROWTH:.0%}")
    disk = [s["disk_kb"] for s in samples if s.get("disk_kb") is not None]
    disk_growth = (disk[-1] - disk[0]) / 1024 if disk else 0.0
    if disk_growth > MAX_DISK_GROWTH_MIB:
        problems.append(f"disk grew {disk_growth:.1f} MiB > {MAX_DISK_GROWTH_MIB} MiB")
    if not rows:
        problems.append("no run settled during the soak")
    ids = Counter(r.get("run_id") for r in rows)
    for run_id, n in sorted(ids.items()):
        if n > 1:
            problems.append(f"duplicate journal run_id: {run_id} x{n}")
    totals = status.get("totals") or {}
    if int(totals.get("runs") or 0) != len(rows):
        problems.append(f"status totals.runs {totals.get('runs')} != journal {len(rows)}")
    for name, value in JOURNAL_TOTALS.items():
        if name in totals and int(totals[name] or 0) != (rebuilt := sum(value(r) for r in rows)):
            problems.append(f"status totals.{name} {totals[name]} != journal {rebuilt}")
    summary = {
        "hours": hours,
        "runs": len(rows),
        "zeny_per_hour": zeny / hours if hours else 0.0,
        "max_heartbeat_gap_s": gap,
        "rss_mib": {"after_warmup": rss[0], "max": rss[1]} if rss else None,
        "disk_growth_mib": disk_growth,
    }
    return not problems, problems, summary


def read_jsonl(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("samples")
    parser.add_argument("journal")
    parser.add_argument("status")
    parser.add_argument("--session", required=True)
    parser.add_argument("--supervisor-exit", type=int, required=True)
    parser.add_argument("--min-hours", type=float, default=0.0)
    args = parser.parse_args()
    journal = read_jsonl(args.journal) if Path(args.journal).exists() else []
    try:
        status = json.loads(Path(args.status).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        status = {}
    ok, problems, summary = verdict(read_jsonl(args.samples), journal, status,
                                    supervisor_exit=args.supervisor_exit, session=args.session,
                                    min_hours=args.min_hours)
    print(json.dumps(summary))
    for problem in problems:
        print(f"soak: FAIL {problem}")
    print("soak: PASS" if ok else "soak: FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
