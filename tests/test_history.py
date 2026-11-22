import json
from datetime import date, datetime

from midgard_farm import platform
from midgard_farm.core.history import append_event, history_path, night_summary, read_history, session_summary, session_timing


def test_history_interleaves_updates_and_ignores_unreadable_or_unknown_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    assert read_history(os_) == []

    append_event(os_, "game_update", old_version="1", new_version="2", result="handled")
    path = history_path(os_)
    first = path.read_bytes()
    with path.open("ab") as file:
        file.write(json.dumps({"v": 2, "kind": "app_update", "future": True}).encode() + b"\n")
        file.write(b'{"v":1,"kind":"app_update","timestamp":42,"future":"additive"}\n')
        file.write(b'{"v":1,"kind":"app_update","timestamp":43,"detail":')
    append_event(os_, "app_update", version="v0.2", result="rolled_back")

    assert path.read_bytes().startswith(first)
    rows = read_history(os_)
    assert [row["kind"] for row in rows] == ["game_update", "app_update", "app_update"]
    assert rows[0]["v"] == 1 and rows[0]["new_version"] == "2"
    assert rows[1]["timestamp"] == 42
    assert rows[2]["result"] == "rolled_back"


def test_session_history_retains_falls_per_run(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    first = {"session": "s", "run_id": "s-r1", "stage": "payon", "danger": 30,
             "falls_by_mechanic": {"Lanzas de Valhalla": 2}}
    second = first | {"run_id": "s-r2", "falls_by_mechanic": {}}
    old = {"session": "s", "run_id": "s-r3", "stage": "payon", "danger": 30}
    (tmp_path / "farmer_runs.jsonl").write_text(
        "\n".join(map(json.dumps, (first, first, second, old))), encoding="utf-8")
    append_event(os_, "session", **session_summary(os_, tmp_path, "s", {}))

    [record] = read_history(os_)
    assert record["run_choices"] == [
        {key: value for key, value in row.items() if key != "session"} for row in (first, second, old)
    ]


def test_session_summary_prefers_journal_outcomes_to_heartbeat_victories(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    os_ = platform.current()
    first = {"session": "s", "run_id": "s-r1", "stage": "payon", "danger": 30}
    rows = [
        first | {"finale_won": True, "forced": True, "victory": False},
        first | {"run_id": "s-r3", "finale_won": False, "victory": True},
        first | {"run_id": "s-r4", "victory": True},
        first | {"run_id": "s-r5", "forced": True, "victory": False},
        first | {"run_id": "s-r6", "stage": "tower", "end_cause": "finish"},
    ]
    (tmp_path / "farmer_runs.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
    totals = session_summary(os_, tmp_path, "s", {"runs": 5, "wins": 1, "losses": 4})["totals"]
    assert (totals["runs"], totals["wins"], totals["losses"]) == (5, 2, 1)


def test_session_timing_uses_elapsed_time_and_keeps_missing_time_unknown():
    row = {"timestamp": 8200, "started_at": 1000, "totals": {"wall_s": 5400}}
    timing = session_timing(row)
    assert (timing.elapsed_s, timing.run_s, timing.downtime_s) == (7200, 5400, 1800)
    assert session_timing(row | {"started_at": None}).downtime_s is None
    assert session_timing(row | {"totals": {}}).downtime_s is None
    assert session_timing(row | {"started_at": 8300}).elapsed_s is None


def test_night_includes_whole_overlapping_sessions_but_not_gaps_or_adjacent_sessions():
    def session(start, end, zeny, wins, runs, run_s):
        return {"kind": "session", "started_at": start.timestamp(), "timestamp": end.timestamp(),
                "totals": {"zeny": zeny, "wins": wins, "runs": runs, "wall_s": run_s}}

    yesterday, today = date(2026, 7, 19), date(2026, 7, 20)
    before, start = datetime(2026, 7, 19, 16), datetime(2026, 7, 19, 18)
    noon, after = datetime(2026, 7, 20, 12), datetime(2026, 7, 20, 13)
    summary = night_summary([
        session(before, start, 9000, 9, 9, 100),
        session(datetime(2026, 7, 19, 17), datetime(2026, 7, 19, 19), 600, 1, 2, 7000),
        session(datetime(2026, 7, 20, 11), after, 1200, 3, 3, 6600),
        session(noon, after, 9000, 9, 9, 100),
        {"kind": "game_update", "timestamp": start.timestamp() + 1},
    ], today)
    assert (summary.sessions, summary.zeny, summary.wins, summary.runs) == (2, 1800, 4, 5)
    assert summary.downtime_s == 800 and not summary.partial_downtime
    assert night_summary([], yesterday).sessions == 0


def test_night_uses_legacy_session_rewards_without_inventing_downtime():
    today = date(2026, 7, 20)
    legacy = {"kind": "session", "timestamp": datetime(2026, 7, 20, 3).timestamp(),
              "totals": {"zeny": 200, "wins": 1, "runs": 2, "wall_s": 500}}
    summary = night_summary([legacy], today)
    assert (summary.sessions, summary.zeny, summary.wins, summary.runs) == (1, 200, 1, 2)
    assert summary.downtime_s is None and summary.partial_downtime
