"""Judge a soak from sampler, run journal and final farmer status artifacts."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

MAX_HEARTBEAT_GAP_S = 15.0
WARMUP_S = 3600.0
MAX_RSS_GROWTH = 0.5
MAX_DISK_GROWTH_MIB = 200
JOURNAL_TOTALS = {
    "wins": lambda r: int(bool(r.get("victory"))),
    "losses": lambda r: int(not r.get("victory")),
    "zeny": lambda r: int(r.get("zeny_gain") or 0),
    "kills": lambda r: int(r.get("kills") or 0),
    "xp": lambda r: int(r.get("xp_gain") or 0),
    "coins": lambda r: int(r.get("coins_gain") or 0),
    "ymir": lambda r: int(r.get("ymir_gain") or 0),
}

def _heartbeat_gap(samples: list[dict]) -> float | None:
    """Longest gap since the first heartbeat, ignoring missing boot/restart status."""
    gap, last_t, last_seq = 0.0, None, None
    for sample in samples:
        seq = sample.get("heartbeat_seq")
        if seq is None or seq == last_seq:
            continue
        if last_t is not None:
            gap = max(gap, sample["t"] - last_t)
        last_t, last_seq = sample["t"], seq
    return None if last_t is None else max(gap, samples[-1]["t"] - last_t)


def _rss_after_warmup(samples: list[dict]) -> tuple[int, int] | None:
    if not samples:
        return None
    t0 = samples[0]["t"]
    late = [s["rss_kb"] // 1024 for s in samples if s["t"] - t0 >= WARMUP_S and s.get("rss_kb")]
    return (late[0], max(late)) if late else None


def _verdict(samples: list[dict], journal: list[dict], status: dict, *, supervisor_exit: int,
             session: str, min_hours: float) -> tuple[bool, list[str], dict[str, Any]]:
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
    gap = _heartbeat_gap(samples)
    if gap is None:
        problems.append("no heartbeat observed")
    elif gap > MAX_HEARTBEAT_GAP_S:
        problems.append(f"heartbeat gap {gap:.1f}s > {MAX_HEARTBEAT_GAP_S}s")
    rss = _rss_after_warmup(samples)
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


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as rows:
        return [json.loads(row) for row in rows if row.strip()]


def judge_files(samples: Path, journal: Path, status: Path, *, session: str, supervisor_exit: int,
                min_hours: float = 0.0) -> tuple[bool, list[str], dict[str, Any]]:
    try:
        final = json.loads(status.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        final = {}
    return _verdict(read_jsonl(samples), read_jsonl(journal) if journal.exists() else [], final,
                    supervisor_exit=supervisor_exit, session=session, min_hours=min_hours)
