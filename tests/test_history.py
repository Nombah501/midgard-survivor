import json

from midgard_farm import platform
from midgard_farm.core.history import append_event, history_path, read_history, session_summary


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
