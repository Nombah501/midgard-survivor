"""Soak verdict from sampler output, the run journal and the final status."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from soak_check import verdict  # noqa: E402

SESSION = "afk-soak"
MIB = 1024


def samples(hours=9.0, every=5.0, rss_kb=lambda t: 900 * MIB, disk_kb=lambda t: 50 * MIB):
    """A healthy sampler log: one heartbeat per sample."""
    rows, t, seq = [], 1_000_000.0, 0
    end = t + hours * 3600
    while t <= end:
        seq += 1
        rows.append({"t": t, "heartbeat_seq": seq, "phase": "run",
                     "rss_kb": rss_kb(t - 1_000_000.0), "disk_kb": disk_kb(t - 1_000_000.0)})
        t += every
    return rows


def journal(n=120, zeny=1000):
    return [{"session": SESSION, "run_id": f"{SESSION}-r{i}", "zeny_gain": zeny, "victory": True}
            for i in range(1, n + 1)]


def final(rows, **over):
    status = {"session": SESSION, "phase": "done", "failed": False, "finish_reason": "max_minutes",
              "totals": {"runs": len(rows), "zeny": sum(r["zeny_gain"] for r in rows)}}
    status.update(over)
    return status


def test_healthy_overnight_soak_passes_and_reports_rewards_per_hour():
    rows = journal()

    ok, problems, summary = verdict(samples(), rows, final(rows), supervisor_exit=0, session=SESSION)

    assert (ok, problems) == (True, [])
    assert summary["hours"] == 9.0
    assert summary["runs"] == 120
    assert summary["zeny_per_hour"] == 120_000 / 9


def test_heartbeat_silent_longer_than_three_intervals_fails_the_soak():
    log = samples()
    stuck = log[100]["heartbeat_seq"]
    for row in log[101:105]:  # 4 more samples, 20 s without a new heartbeat
        row["heartbeat_seq"] = stuck
    rows = journal()

    ok, problems, summary = verdict(log, rows, final(rows), supervisor_exit=0, session=SESSION)

    assert not ok
    assert summary["max_heartbeat_gap_s"] == 25.0
    assert problems == ["heartbeat gap 25.0s > 15.0s"]


def test_memory_growth_after_warmup_hour_fails_but_warmup_does_not():
    def rss(t):  # 400 MiB at boot, 1000 MiB after warmup, then +700 MiB by the end
        if t < 3600:
            return 400 * MIB + int(600 * MIB * t / 3600)
        return 1000 * MIB + int(700 * MIB * (t - 3600) / (8 * 3600))
    rows = journal()

    ok, problems, summary = verdict(samples(rss_kb=rss), rows, final(rows), supervisor_exit=0, session=SESSION)

    assert not ok
    assert summary["rss_mib"] == {"after_warmup": 1000, "max": 1700}
    assert problems == ["game RSS grew 70% after the first hour (1000 -> 1700 MiB) > 50%"]


def test_disk_growth_over_200_mib_fails_the_soak():
    rows = journal()
    log = samples(disk_kb=lambda t: 50 * MIB + int(260 * MIB * t / (9 * 3600)))

    ok, problems, summary = verdict(log, rows, final(rows), supervisor_exit=0, session=SESSION)

    assert not ok
    assert summary["disk_growth_mib"] == 260
    assert problems == ["disk grew 260.0 MiB > 200 MiB"]


def test_double_settlement_or_drifting_totals_fail_the_soak():
    rows = journal()
    doubled = rows + [dict(rows[41])]  # r42 journaled twice
    other_session = [{**rows[0], "session": "afk-earlier"}]  # not this soak's

    ok, problems, _ = verdict(samples(), doubled + other_session, final(rows), supervisor_exit=0, session=SESSION)

    assert not ok
    assert problems == [
        "duplicate journal run_id: afk-soak-r42 x2",
        "status totals.runs 120 != journal 121",
        "status totals.zeny 120000 != journal 121000",
    ]


def test_quarantine_or_failed_finish_fails_the_soak():
    rows = journal()

    ok, problems, _ = verdict(samples(), rows, final(rows, phase="failed", failed=True,
                                                       finish_reason="flush_failed"),
                              supervisor_exit=2, session=SESSION)

    assert not ok
    assert problems == ["supervisor exit 2 (quarantine)", "farmer did not finish cleanly: failed/flush_failed"]


def test_soak_shorter_than_requested_fails():
    rows = journal()

    ok, problems, _ = verdict(samples(hours=6.5), rows, final(rows), supervisor_exit=0,
                              session=SESSION, min_hours=8.0)

    assert not ok
    assert problems == ["soak lasted 6.5 h < 8.0 h"]


def test_boot_without_status_is_not_a_gap_but_no_heartbeat_at_all_fails():
    rows = journal()
    log = samples()
    for row in log[:30]:  # 150 s of game boot before the first status
        row["heartbeat_seq"] = None

    assert verdict(log, rows, final(rows), supervisor_exit=0, session=SESSION)[0]

    for row in log:
        row["heartbeat_seq"] = None
    ok, problems, _ = verdict(log, rows, final(rows), supervisor_exit=0, session=SESSION)
    assert not ok
    assert problems == ["no heartbeat observed"]


def test_soak_without_settled_runs_fails():
    ok, problems, _ = verdict(samples(), [], final([]), supervisor_exit=0, session=SESSION)

    assert not ok
    assert problems == ["no run settled during the soak"]


def test_every_journal_backed_total_must_match():
    rows = [{**r, "kills": 50, "xp_gain": 7, "coins_gain": 1, "ymir_gain": 0, "victory": i % 2 == 0}
            for i, r in enumerate(journal(n=10))]
    status = final(rows)
    status["totals"].update({"kills": 499, "xp": 70, "coins": 10, "ymir": 0, "wins": 5, "losses": 5})

    ok, problems, _ = verdict(samples(), rows, status, supervisor_exit=0, session=SESSION)

    assert not ok
    assert problems == ["status totals.kills 499 != journal 500"]


def test_disk_growth_is_compared_before_rounding():
    rows = journal()
    log = samples(disk_kb=lambda t: 50 * MIB + (200 * MIB + 1 if t > 3600 else 0))

    ok, problems, _ = verdict(log, rows, final(rows), supervisor_exit=0, session=SESSION)

    assert not ok
    assert problems == ["disk grew 200.0 MiB > 200 MiB"]
