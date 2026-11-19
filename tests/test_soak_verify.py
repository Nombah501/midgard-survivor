"""The new soak judge and the legacy command see the same sampler artifacts."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from midgard_farm.verify.soak import judge_files

SESSION = "afk-soak"
LEGACY = Path(__file__).resolve().parents[1] / "farmer/tools/soak_check.py"
MIB = 1024

CASES = {
    "healthy": [],
    "heartbeat-stall": ["heartbeat gap 25.0s > 15.0s"],
    "rss-growth": ["game RSS grew 70% after the first hour (1000 -> 1700 MiB) > 50%"],
    "disk-growth": ["disk grew 260.0 MiB > 200 MiB"],
    "duplicates": ["duplicate journal run_id: afk-soak-r42 x2", "status totals.runs 120 != journal 121",
                   "status totals.zeny 120000 != journal 121000"],
    "quarantine": ["supervisor exit 2 (quarantine)", "farmer did not finish cleanly: failed/flush_failed"],
    "too-short": ["soak lasted 6.5 h < 8.0 h"],
    "slow-boot": [],
    "no-heartbeat": ["no heartbeat observed"],
    "no-settlement": ["no run settled during the soak"],
    "backed-totals": ["status totals.kills 499 != journal 500"],
    "unrounded-disk-growth": ["disk grew 200.0 MiB > 200 MiB"],
    "no-rss-after-warmup": ["no game RSS sample after the first hour"],
}


@pytest.fixture(params=CASES)
def soak_artifacts(request, tmp_path):
    case = request.param
    hours = 6.5 if case == "too-short" else 1 if case == "no-rss-after-warmup" else 9
    supervisor_exit, min_hours = 0, 0
    journal = [{"session": SESSION, "run_id": f"{SESSION}-r{i}", "zeny_gain": 1000, "victory": True}
               for i in range(1, 121)]
    if case == "no-settlement":
        journal.clear()
    if case == "backed-totals":
        journal = [{**r, "kills": 50, "xp_gain": 7, "coins_gain": 1, "ymir_gain": 0, "victory": i % 2 == 0}
                   for i, r in enumerate(journal[:10])]
    totals = {"runs": len(journal), "zeny": sum(r["zeny_gain"] for r in journal)}
    status = {"session": SESSION, "phase": "done", "failed": False, "finish_reason": "max_minutes",
              "totals": totals}
    if case == "backed-totals":
        totals.update(kills=499, xp=70, coins=10, ymir=0, wins=5, losses=5)
    if case == "duplicates":
        journal += [dict(journal[41]), {**journal[0], "session": "afk-earlier"}]
    if case == "quarantine":
        supervisor_exit = 2
        status.update(phase="failed", failed=True, finish_reason="flush_failed")
    if case == "too-short":
        min_hours = 8
    samples = []
    for i, t in enumerate(range(0, int(hours * 3600) + 1, 5)):
        seq = i + 1
        rss, disk = 900 * MIB, 50 * MIB
        if case == "heartbeat-stall" and 101 <= i < 105:
            seq = 101
        if case == "slow-boot" and i < 30 or case == "no-heartbeat":
            seq = None
        if case == "rss-growth":
            rss = (400 * MIB + int(600 * MIB * t / 3600) if t < 3600
                   else 1000 * MIB + int(700 * MIB * (t - 3600) / (8 * 3600)))
        if case == "disk-growth":
            disk += int(260 * MIB * t / (9 * 3600))
        if case == "unrounded-disk-growth" and t > 3600:
            disk += 200 * MIB + 1
        if case == "no-rss-after-warmup" and t == 3600:
            rss = None
        samples.append({"t": 1_000_000 + t, "phase": "run", "heartbeat_seq": seq, "rss_kb": rss, "disk_kb": disk})
    paths = [tmp_path / name for name in ("samples.jsonl", "journal.jsonl", "status.json")]
    paths[0].write_text("\n".join(map(json.dumps, samples)), encoding="utf-8")
    if journal:
        paths[1].write_text("\n".join(map(json.dumps, journal)), encoding="utf-8")
    paths[2].write_text(json.dumps(status), encoding="utf-8")
    return case, paths, {"session": SESSION, "supervisor_exit": supervisor_exit, "min_hours": min_hours}


def test_soak_judge_matches_documented_cases(soak_artifacts):
    case, paths, settings = soak_artifacts
    ok, problems, summary = judge_files(*paths, **settings)
    assert problems == CASES[case]
    assert ok is (not problems)
    if case == "healthy":
        assert summary == {"hours": 9.0, "runs": 120, "zeny_per_hour": 120_000 / 9, "max_heartbeat_gap_s": 5.0,
                           "rss_mib": {"after_warmup": 900, "max": 900}, "disk_growth_mib": 0.0}


@pytest.mark.skipif(not LEGACY.is_file(), reason="legacy soak checker removed at cutover")
def test_soak_judge_has_exact_legacy_cli_parity(soak_artifacts):
    _, paths, settings = soak_artifacts
    legacy = subprocess.run(
        [sys.executable, str(LEGACY), *map(str, paths), "--session", SESSION,
         "--supervisor-exit", str(settings["supervisor_exit"]), "--min-hours", str(settings["min_hours"])],
        check=False, capture_output=True, text=True,
    )
    ok, problems, summary = judge_files(*paths, **settings)
    lines = legacy.stdout.splitlines()
    assert legacy.returncode == (0 if ok else 1), legacy.stderr
    assert json.loads(lines[0]) == summary
    assert lines[1:-1] == [f"soak: FAIL {problem}" for problem in problems]
    assert lines[-1] == ("soak: PASS" if ok else "soak: FAIL")
