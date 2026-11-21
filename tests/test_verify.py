"""Drive the verification runner with real sandboxes/supervision and a fake game."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from threading import Event, Thread

import pytest

from midgard_farm import platform
from midgard_farm.core import commands, farmer_patch, patch_info, supervisor
from midgard_farm.core.state import StateReporter
from midgard_farm.verify import scenarios
from test_profile import make_profile

ALL = (
    "one-run", "catalog", "preparation-unchanged", "wishlist-keep", "run-choice", "run-choice-resume",
    "location-rotation", "location-rotation-resume",
    "oaths", "oaths-disabled", "invalid-oath", "invalid-oath-rank", "invalid-oath-difficulty", "invalid-location",
    "invalid-difficulty", "invalid-rotation-difficulty", "stop", "endless", "hell-rotation",
    "hell-rotation-payon", "hell-rotation-orc_dun", "hell-rotation-nameless", "hell-rotation-turtle",
    "valkyrie-drill", "mvp-mechanics-drill",
    "blocked-portal", "field-navigation", "field-charge-drill", "flush-fail",
    "crash-run", "crash-settled", "crash-journaled",
    "cmd-finish", "cmd-abort", "cmd-abort-settled", "cmd-pause-resume", "cmd-legacy", "checkpoint-corrupt",
    "supervised-kill-run", "supervised-crash-settled", "run-stall",
)


class VerifyGamePlatform(type(platform.current())):
    game_exe_name = "verify-fixture.exe" if sys.platform == "win32" else "verify-fixture"
    release_os = os.environ.get("FAKE_VERIFY_RELEASE_OS", platform.current().release_os)
    tree = None

    def check_network_isolation(self):
        return None

    def notify_desktop(self, *_):
        pytest.fail("verification must not send notifications")

    def game_pids(self):
        if os.environ.get("FAKE_VERIFY_GAME_RUNNING") == "1":
            return {os.getpid()}
        return {self.tree.popen.pid} if self.tree is not None and self.tree.popen.poll() is None else set()

    def spawn_tree(self, argv, *, isolate_network=False, **kwargs):
        assert isolate_network
        fake = Path(__file__).with_name("fake_verify_game.py")
        self.tree = super().spawn_tree([sys.executable, str(fake), *argv[1:]], **kwargs)
        return self.tree


@pytest.fixture
def verification(tmp_path, monkeypatch):
    os_ = VerifyGamePlatform()
    work = tmp_path / "suite" / "sandbox" / "attempt"
    work.mkdir(parents=True)
    out = work.parents[1]
    root, _ = os_.godot_sandbox(work)
    for key, value in os_.app_sandbox_environment(work).items():
        if os.environ.get(key) != value:
            monkeypatch.setenv(key, value)
    monkeypatch.setenv("GAME_DIR", str(tmp_path))
    monkeypatch.setenv("FARMER_DISPLAY", "1")  # Not part of verification config.
    monkeypatch.setenv("FARMER_TEST_FLUSH_FAIL", "1")  # Must not leak to unrelated scenarios.
    monkeypatch.setenv("FARMER_BACKUP_DIR", str(tmp_path / "real backups"))
    exe = os_.game_executable()
    exe.touch()
    exe.chmod(0o755)
    source = make_profile(tmp_path / "real", "Renamed Profile")
    monkeypatch.setenv("FAKE_VERIFY_SOURCE", str(source))
    (source / "profile.json").write_text("100", encoding="utf-8")
    (source / "farmer_command").write_text("real command must survive", encoding="utf-8")
    patches = source / "patches"
    official_state = b'{"file":"official.pck", "version":"1"}'
    (patches / "official-state.json").write_bytes(official_state)
    (patches / "state.json").write_bytes(b'{"file":"patch_farmer.pck", "farmer":1, "version":"1"}')
    (patches / patch_info.INSTALLED_PACK).write_bytes(b"installed farmer pack")
    official = b"official patch bytes"
    (patches / "official.pck").write_bytes(official)
    candidate = tmp_path / "candidate"
    pack = b"built farmer pack"
    info = patch_info.PatchInfo("official.pck", "1", hashlib.sha256(official).hexdigest(), "", "", "ebc36a7", 3,
                               farmer_patch.farmer_hash(), hashlib.sha256(pack).hexdigest(), "fixture")
    patch_info.save(os_, candidate / "patch_farmer.json", info)
    (candidate / patch_info.INSTALLED_PACK).write_bytes(pack)
    return os_, source, candidate, work, out, root


def execute(verification, name, **kwargs):
    os_, source, candidate, work, out, _ = verification
    return scenarios.run_scenario(os_, source, candidate, work, out, name,
                                  policy=supervisor.Policy(backoff_base=0.05), **kwargs)


def test_registry_contains_every_legacy_scenario():
    assert scenarios.BOUNDED_SCENARIOS == ALL


@pytest.mark.parametrize("name", ALL)
def test_verifies_every_scenario_against_a_fake_game(verification, name):
    os_, source, _, _, out, root = verification
    if name == "supervised-kill-run" and os_.release_os != "linux":
        with pytest.raises(ValueError, match="unsupported on this OS"):
            execute(verification, name)
        return

    protected = [source / "patches" / name for name in ("state.json", patch_info.INSTALLED_PACK)]
    before = [path.read_bytes() for path in protected]
    row = execute(verification, name)

    assert row["verdict"] == "PASS", row
    assert json.loads((out / f"{name}.result.json").read_text()) == row
    assert (out / f"{name}.run.log").exists()
    config = json.loads((out / f"{name}.json").read_text()) if name in {"hell-rotation", "one-run"} else {}
    if name == "hell-rotation":
        assert (config["altar_policy"], config["karma_route"]) == ("map-wide", "valhalla")
    elif name == "one-run":
        assert "altar_policy" not in config and "karma_route" not in config
    if name == "catalog":
        assert (out / "catalog.catalog.json").is_file()
    assert (root / source.name / "patches" / "official.pck").samefile(source / "patches/official.pck")
    assert (source / "profile.json").read_text() == "100"
    assert [path.read_bytes() for path in protected] == before
    assert (source / "farmer_command").read_text() == "real command must survive"
    assert not (source.parents[1] / "real backups").exists()
    assert not os_.game_running()
    if name.startswith("supervised-"):
        logdir, = (out / f"{name}.supervisor").glob("supervisor-verify-*")
        outcome = json.loads((logdir / "outcome.json").read_text())
        assert [(a["number"], a["outcome"]) for a in outcome["attempts"]] == [(1, "failed"), (2, "finished")]
        assert len(list(logdir.glob("attempt-*.log"))) == 2


def test_windowed_scenario_finishes_one_supervised_attempt(verification, monkeypatch):
    _, _, _, _, out, root = verification
    monkeypatch.setenv("FAKE_VERIFY_WATCH_MODE", "1")
    result = execute(verification, "watch-mode")
    assert result["verdict"] == "PASS" and result["exit"] == 0 and result["runs"] == 1, result
    assert json.loads(next(root.glob("*/farmer.cfg")).read_bytes())["display"] is True
    assert "display" not in json.loads((out / "watch-mode.strategy.json").read_bytes())


@pytest.mark.parametrize(("fault", "reason"), [
    ("no-victory", "PLAYER_DIED t=1842.0 by=Orc Warrior what=Bash"),
    ("no-finale", "final boss"),
    ("forced-finale", "run_timeout"),
    ("paid-finale-keep", "three free keep slots"),
    ("wrong-oath-journal-points", "oath points"),
    ("wrong-run-journal-target", "location or difficulty"),
    ("no-altars", "no map-wide altar taken"),
    ("took-hel", "took an altar not allowed"),
    ("baldur-in-field", "Baldur taken outside portal window"),
    ("wrong-baldur-skip", "invalid Baldur field skip"),
    ("interrupted-altar-taken", "took an altar after its channel was interrupted"),
    ("no-second-route", "no Valhalla route after MVP 3"),
    ("no-second-valkyrie", "no Valkyrie kill before endless continued after MVP 3"),
    ("late-valkyrie", "no Valkyrie kill before endless continued after MVP 3"),
    ("missing-mvp-log", "MVP count does not match"),
    ("uncounted-finale-mvp", "MVP count does not match"),
])
def test_hell_rotation_requires_a_real_finale_win(verification, monkeypatch, fault, reason):
    monkeypatch.setenv("FAKE_VERIFY_FAULT", fault)
    row = execute(verification, "hell-rotation")
    assert row["verdict"] == "FAIL" and reason in row["reason"], row


@pytest.mark.parametrize(("name", "fault", "reason"), [
    ("one-run", "no-transition", "last_transition empty"),
    ("one-run", "no-victory", "last run was not a victory"),
    ("catalog", "no-catalog", "no valid catalog"),
    ("catalog", "empty-locations", "wrong location unlocks"),
    ("preparation-unchanged", "rerolled-worn-item", "character preparation changed: potentials"),
    ("preparation-unchanged", "reset-saved-auto-pick", "character preparation changed: endless_auto_pick"),
    ("preparation-unchanged", "no-native-auto-pick", "native auto-pick did not apply a level-up"),
    ("preparation-unchanged", "no-free-points", "the starting character must have unspent stat points"),
    ("wishlist-keep", "duplicate-wishlist-item", "wrong items added to saved storage"),
    ("wishlist-keep", "no-wishlist-cash-in", "legendary offers were not cashed in"),
    ("run-choice", "wrong-run-journal-target", "wrong location or difficulty in journal"),
    ("location-rotation", "locked-rotation-location", "wrong location or difficulty in journal"),
    ("oaths", "wrong-oath-journal-points", "wrong oath points in journal"),
    ("oaths", "changed-saved-oaths", "saved oath set changed"),
    ("invalid-location", "no-choice-diagnostic", "failure detail did not name the invalid field and value"),
    ("stop", "script-error", "script error"),
    ("endless", "no-mvp", "endless_mvps == 0"),
    ("blocked-portal", "portal-not-entered", "BLOCKED_PORTAL entered"),
    ("field-navigation", "altar-expired-instead", "reason=expires_first"),
    ("field-navigation", "maze-stall", "FIELD_NAVIGATION collected"),
    ("field-navigation", "pocket-stall", "FIELD_NAVIGATION escaped"),
    ("field-charge-drill", "charge-contact", "field charge hit the hero"),
    ("valkyrie-drill", "meteor-hit", "Caída de Valhalla hit or killed the hero"),
    ("valkyrie-drill", "meteor-contact", "Caída de Valhalla hit or killed the hero"),
    ("valkyrie-drill", "meteor-incomplete", "expected ten complete six-mark"),
    ("mvp-mechanics-drill", "mvp-contact", "MVP drill mechanic hit or killed the hero"),
    ("mvp-mechanics-drill", "mvp-incomplete", "MVP drill did not witness every strike"),
    ("mvp-mechanics-drill", "mvp-fall", "MVP drill journal has missing or nonzero fall counts"),
    ("crash-settled", "unbanked-zeny", "profile zeny moved"),
    ("supervised-crash-settled", "duplicate-journal", "duplicate journal run_id"),
    ("cmd-pause-resume", "pause-starts-run", "paused farmer started another run"),
    ("cmd-abort-settled", "kept-on-abort", "abort kept an item"),
    ("checkpoint-corrupt", "profile-mutated", "profile changed"),
    ("run-stall", "unforced-stall", "frozen run was not forced"),
])
def test_judges_reject_wrong_evidence(verification, monkeypatch, name, fault, reason):
    monkeypatch.setenv("FAKE_VERIFY_FAULT", fault)
    result = execute(verification, name)
    assert result["verdict"] == "FAIL"
    assert reason in result["reason"]


def test_cli_requires_explicit_live_selection(tmp_path):
    invocation = [sys.executable, "-m", "midgard_farm.verify"]
    help_ = subprocess.run([*invocation, "--help"], cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert help_.returncode == 0 and all(flag in help_.stdout for flag in ("--scenario", "--all", "--soak", "--keep"))
    no_selection = subprocess.run(invocation, cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert no_selection.returncode == 2
    assert not list(tmp_path.iterdir())


@pytest.fixture
def fake_cli(verification, tmp_path):
    os_, source, candidate, work, _, _ = verification
    real = tmp_path / "source-home"
    root, _ = os_.godot_sandbox(real)
    root.mkdir(parents=True)
    profile = root / source.name
    shutil.move(source, profile)
    env = os_.app_sandbox_environment(real)
    # Both the CLI and its worker use the fixture game instead of the real executable.
    harness = tmp_path / "harness"
    harness.mkdir()
    (harness / "sitecustomize.py").write_text(
        "from test_verify import VerifyGamePlatform\n"
        "from midgard_farm import platform\nplatform.current = VerifyGamePlatform\n", encoding="utf-8",
    )
    env.update(PYTHONPATH=os.pathsep.join((str(harness), str(Path(__file__).resolve().parent))),
               HOME=str(tmp_path), USERPROFILE=str(tmp_path), FAKE_VERIFY_SOURCE=str(profile))

    def invoke(*args, timeout=60, **overrides):
        invocation = [sys.executable, "-B", "-m", "midgard_farm.verify", *args]
        return subprocess.run(invocation, env=env | overrides, cwd=tmp_path, capture_output=True, text=True, timeout=timeout)

    return os_, real, profile, candidate, work, invoke


@pytest.mark.parametrize(("keep", "fault"), [(False, ""), (True, ""), (False, "no-victory")])
def test_cli_retains_logs_and_only_keeps_requested_or_failed_sandboxes(fake_cli, tmp_path, keep, fault):
    os_, real, profile, candidate, _, invoke = fake_cli
    flags = ["--keep"] if keep else []
    result = invoke("--scenario", "one-run", "--candidate-dir", str(candidate), *flags, FAKE_VERIFY_FAULT=fault)
    assert result.returncode == bool(fault), result.stdout + result.stderr
    out, = (tmp_path / ".sandbox").glob("verify-*")
    summary = json.loads((out / "summary.json").read_bytes())
    assert summary["rows"][0]["verdict"] == ("FAIL" if fault else "PASS")
    assert (out / "one-run.run.log").is_file()
    assert (out / "sandbox").exists() == bool(keep or fault)
    assert (profile / "profile.json").read_text() == "100"
    assert not (real / os_.app_data_dir().name).exists()


def test_cli_all_runs_supported_scenarios_and_reports_windows_skip(fake_cli, tmp_path):
    _, _, _, candidate, _, invoke = fake_cli
    result = invoke("--all", "--candidate-dir", str(candidate), timeout=120, FAKE_VERIFY_RELEASE_OS="windows")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "supervised-kill-run is Linux only (unsupported on this OS)" in result.stdout
    out, = (tmp_path / ".sandbox").glob("verify-*")
    rows = json.loads((out / "summary.json").read_bytes())["rows"]
    assert [(row["scenario"], row["verdict"]) for row in rows] == [
        (name, "SKIP" if name == "supervised-kill-run" else "PASS") for name in ALL
    ]
    assert not (out / "supervised-kill-run.worker.log").exists()

    explicit = invoke("--scenario", "supervised-kill-run", FAKE_VERIFY_RELEASE_OS="windows")
    assert explicit.returncode == 2 and "unsupported on this OS" in explicit.stderr


def test_cli_refuses_to_start_while_game_is_running(fake_cli, tmp_path):
    _, _, profile, candidate, _, invoke = fake_cli
    result = invoke("--scenario", "one-run", "--candidate-dir", str(candidate), FAKE_VERIFY_GAME_RUNNING="1")
    assert result.returncode == 2 and "the game is running" in result.stderr
    assert not list((tmp_path / ".sandbox").glob("verify-*"))
    assert (profile / "profile.json").read_text() == "100"


def test_direct_worker_cannot_bypass_suite_locks(fake_cli):
    os_, _, profile, candidate, work, invoke = fake_cli
    env = {k: v for k, v in os_.app_sandbox_environment(work).items() if k in {"XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA"}}
    result = invoke("_worker", "not-issued-by-parent", str(profile), str(candidate), str(work), "one-run", "0", "", **env)
    assert result.returncode == 2 and "must be launched by the verification CLI" in result.stderr
    assert not list(work.iterdir())


def test_lock_queues_and_can_time_out(tmp_path, capsys):
    from midgard_farm.verify.__main__ import wait_for_lock

    os_ = platform.current()
    lock = tmp_path / "verify.lock"
    ready, release = Event(), Event()

    def hold():
        with os_.acquire_lock(lock):
            ready.set()
            release.wait(10)

    thread = Thread(target=hold)
    thread.start()
    try:
        assert ready.wait(3)
        with pytest.raises(TimeoutError, match="verify.lock"):
            wait_for_lock(os_, lock, time.monotonic(), lambda: None)
        assert "waiting" in capsys.readouterr().out
    finally:
        release.set()
        thread.join()
    with wait_for_lock(os_, lock, time.monotonic() + 1, lambda: None):
        with pytest.raises(platform.LockHeld):
            os_.acquire_lock(lock)


def test_direct_deadline_kills_only_the_sandbox_game(verification, monkeypatch):
    from dataclasses import replace

    monkeypatch.setenv("FAKE_VERIFY_FAULT", "hang")
    monkeypatch.setitem(scenarios.SCENARIOS, "one-run", replace(scenarios.SCENARIOS["one-run"], timeout=0.3))
    result = execute(verification, "one-run")
    assert result["verdict"] == "FAIL" and result["exit"] == 124
    assert not verification[0].game_running()


@pytest.mark.parametrize("custom", [False, True])
def test_soak_samples_real_supervisor_with_fake_game(verification, tmp_path, custom):
    os_, _, _, _, out, root = verification
    if os_.release_os != "linux":
        with pytest.raises(ValueError, match="Linux only"):
            execute(verification, "soak", hours=0.00001)
        return
    preset = None
    if custom:
        preset = tmp_path / "custom.json"
        preset.write_text(json.dumps({"builds": {"archer": {"job_path": 1}},
                                      "job_paths": {"swordsman": 2}}))
    row = execute(verification, "soak", hours=0.00001, soak_preset=preset)
    assert row["verdict"] == "FAIL" and row["exit"] == 0  # No post-warmup RSS in this intentionally short run.
    verdict = (out / "soak.verdict.log").read_text()
    assert "no game RSS sample after the first hour" in verdict
    summary = json.loads(verdict.splitlines()[0])
    assert summary["runs"] == 1
    config = json.loads(next(root.glob("*/farmer.cfg")).read_text())
    assert config["stage"] == "" and config["danger"] == "auto" and config["max_minutes"] == 0.00001 * 60
    if custom:
        assert config["builds"] == {"archer": {"job_path": 1}}
        assert config["job_paths"] == {"swordsman": 2} and not config["display"]
    samples = [json.loads(line) for line in (out / "soak.samples.jsonl").read_text().splitlines()]
    assert samples[0]["heartbeat_seq"] is None and samples[-1]["phase"] == "done"
    assert len(samples) >= 2 and all(isinstance(sample["disk_kb"], int) for sample in samples)


@pytest.mark.parametrize(("mode", "saved", "accept"), [
    ("verify", "verify", True), ("afk", "afk", True), ("verify", "afk", False), ("afk", "verify", False),
])
def test_supervisor_recovers_only_its_configured_session_prefix(verification, mode, saved, accept):
    os_, _, _, _, out, root = verification
    profile = make_profile(root, "Sandbox Profile")
    session = f"{saved}-{'1' * 32}"
    request = commands.submit(os_, commands.Start(commands.Character("swordsman", 0), out / "preset.json"))
    session_path = os_.app_data_dir() / "session.json"
    session_path.write_text(json.dumps({"id": session, "profile": str(profile),
                                        "start": json.loads(request.read_text()), "request": request.name}))
    # Recover a terminal record without playing a game; rebuilding/history are real core operations.
    log_dir = os_.app_data_dir() / "logs" / f"supervisor-{session}"
    log_dir.mkdir(parents=True)
    (log_dir / "outcome.json").write_text(json.dumps({"session": session, "kind": "finished", "reason": "finish",
                                                    "attempts": [], "totals": {}}))
    with StateReporter(os_) as reporter:
        driver = supervisor.Supervisor(os_, profile, supervisor.Policy(), lambda: 1.0, lambda *_: None,
                                       state=reporter, session_prefix=mode)
        if accept:
            driver.run()
            assert not request.exists() and not session_path.exists()
            assert session in (os_.app_data_dir() / "history.jsonl").read_text()
        else:
            with pytest.raises(supervisor.InvalidSavedSession, match="invalid saved AFK session id"):
                driver.run()
            assert request.exists() and session_path.exists()
