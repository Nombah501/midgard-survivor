#!/usr/bin/env bash
# Bounded end-to-end verification of the farmer.
#
# Runs one or more scenarios against a throwaway copy of the real user://
# profile. The real profile is only read. Each scenario has its own timeout;
# a timeout, a non-zero exit, a missing status, or a failed assertion is FAIL.
#
# Usage: ./tools/verify.sh [--one-run] [--stop] [--endless] [--flush-fail]
#                          [--crash-run] [--crash-settled] [--crash-journaled]
#                          [--cmd-finish] [--cmd-abort] [--cmd-abort-settled]
#                          [--cmd-pause-resume] [--cmd-legacy] [--checkpoint-corrupt]
#                          [--supervised-kill-run] [--supervised-crash-settled]
#                          [--all] [--keep]
#        ./tools/verify.sh --soak=HOURS [--soak-preset=JSON] [--keep]
# Default: --all (every scenario except the soak).
#
# --crash-* kill the farmer at one checkpoint boundary (run start, after
# settlement, after the journal write), relaunch the same session and assert
# that totals and the journal hold every settled run exactly once.
#
# --cmd-* publish commands inside the sandbox and check heartbeat and accounting.
#
# --supervised-* run the real supervisor: SIGKILL the game before settlement
# (from outside) or after it (one-shot in-farmer hook); the supervisor restarts
# the farmer, which must continue the session without a second settlement.
#
# --soak=HOURS uses modes/short.json by default, with max_minutes=HOURS*60,
# under the supervisor, samples heartbeat, game RSS and disk every 5 s and
# judges the result with tools/soak_check.py (heartbeat gap, RSS after the
# first hour, disk growth, duplicate run_id, totals == journal).
#
# Artifacts: farmer/logs/verify-<stamp>/{summary.json,*.log,*.status.json}
set -euo pipefail

# Parsed whole before it runs; safe to edit during a verification (see run.sh).
main() {

FARMER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(cd "$FARMER_DIR/.." && pwd)"
GAME_DIR="${GAME_DIR:-$HOME/games/midgard-survivors}"
REAL_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/godot/app_userdata/Midgard Survivors"
INFO="$FARMER_DIR/patch_farmer.info"
PCK="$FARMER_DIR/patch_farmer.pck"
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
OUT_DIR="$FARMER_DIR/logs/verify-$STAMP"
SB="${VERIFY_SANDBOX:-$REPO_DIR/.sandbox/verify-$STAMP}"
export FARMER_BACKUP_DIR="$SB/backups"
SB_DATA="$SB/godot/app_userdata/Midgard Survivors"
SNAP="$SB/snapshot"
KEEP=0
FAILED=0
SCENARIOS=()
SOAK_HOURS=""
SOAK_STRATEGY="$FARMER_DIR/modes/short.json"
ALL_SCENARIOS=(one-run stop endless flush-fail crash-run crash-settled crash-journaled
	cmd-finish cmd-abort cmd-abort-settled cmd-pause-resume cmd-legacy checkpoint-corrupt
	supervised-kill-run supervised-crash-settled)

usage() {
	awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

die() {
	echo "verify: $*" >&2
	echo "verify: artifacts $OUT_DIR" >&2
	exit 2
}

for arg in "$@"; do
	case "$arg" in
		--one-run) SCENARIOS+=(one-run) ;;
		--stop) SCENARIOS+=(stop) ;;
		--endless) SCENARIOS+=(endless) ;;
		--flush-fail) SCENARIOS+=(flush-fail) ;;
		--crash-run) SCENARIOS+=(crash-run) ;;
		--crash-settled) SCENARIOS+=(crash-settled) ;;
		--crash-journaled) SCENARIOS+=(crash-journaled) ;;
		--cmd-finish|--cmd-abort|--cmd-abort-settled|--cmd-pause-resume|--cmd-legacy|--checkpoint-corrupt|\
		--supervised-kill-run|--supervised-crash-settled)
			SCENARIOS+=("${arg#--}") ;;
		--soak=*) SOAK_HOURS="${arg#--soak=}"; SCENARIOS+=(soak) ;;
		--soak-preset=*) SOAK_STRATEGY="$(realpath -- "${arg#--soak-preset=}")" ;;
		--all) SCENARIOS=("${ALL_SCENARIOS[@]}") ;;
		--keep) KEEP=1 ;;
		-h|--help) usage; exit 0 ;;
		*) die "unknown argument: $arg" ;;
	esac
done
if [[ ${#SCENARIOS[@]} -eq 0 ]]; then
	SCENARIOS=("${ALL_SCENARIOS[@]}")
fi
if [[ -n "$SOAK_HOURS" ]]; then
	[[ "$SOAK_HOURS" =~ ^[0-9]+([.][0-9]+)?$ ]] || die "--soak needs a number of hours, got: $SOAK_HOURS"
	[[ -f "$SOAK_STRATEGY" ]] || die "soak strategy not found: $SOAK_STRATEGY"
fi

# One game process per machine: concurrent verifications queue here instead
# of racing for the game (VERIFY_LOCK_WAIT seconds, default 1 h).
mkdir -p "$REPO_DIR/.sandbox"
exec 8>"$REPO_DIR/.sandbox/verify.lock"
if ! flock -n 8; then
	echo "verify: another verification holds .sandbox/verify.lock; waiting"
	flock -w "${VERIFY_LOCK_WAIT:-3600}" 8 || die "timed out waiting for .sandbox/verify.lock"
fi

[[ -x "$GAME_DIR/MidgardSurvivors.x86_64" ]] || die "game not found at $GAME_DIR"
[[ -f "$REAL_DATA/profile.json" ]] || die "real profile not found at $REAL_DATA"
[[ -f "$INFO" && -f "$PCK" ]] || die "build first: ./build.sh"
PCK_SHA="$(sha256sum "$PCK" | cut -d' ' -f1)"
INFO_SHA="$(sed -n 's/^PATCH_FARMER_SHA256=//p' "$INFO")"
[[ "$PCK_SHA" == "$INFO_SHA" ]] || die "patch_farmer.pck does not match patch_farmer.info; rebuild"
if pgrep -f 'MidgardSurvivors\.x86_64' >/dev/null 2>&1; then
	die "the game is running; close it first (verify never touches the real profile)"
fi
[[ -x "$FARMER_DIR/tools/check.sh" ]] || die "tools/check.sh missing"

mkdir -p "$OUT_DIR" "$SB_DATA/patches"

# Copy the real user:// tree, but hardlink the large, read-only .pck files when
# the filesystem allows it. install.sh replaces files with rename, so the
# originals are never modified through a link.
for entry in "$REAL_DATA"/*; do
	name="$(basename "$entry")"
	if [[ "$name" == "patches" ]]; then
		continue
	fi
	cp -a "$entry" "$SB_DATA/"
done
for entry in "$REAL_DATA/patches"/*; do
	name="$(basename "$entry")"
	size="$(stat -c %s "$entry" 2>/dev/null || echo 0)"
	if [[ "$name" == *.pck && "$size" -gt 20000000 ]]; then
		ln "$entry" "$SB_DATA/patches/$name" 2>/dev/null || cp -a "$entry" "$SB_DATA/patches/$name"
	else
		cp -a "$entry" "$SB_DATA/patches/$name"
	fi
done

mkdir -p "$SNAP"
for name in profile.json profile.bak.json profile.run profile.run.farmer_bak; do
	if [[ -f "$SB_DATA/$name" ]]; then
		cp -a "$SB_DATA/$name" "$SNAP/$name"
	fi
done

echo "verify: sandbox $SB"
echo "verify: build   $PCK_SHA"
echo "verify: output  $OUT_DIR"
echo

if ! "$FARMER_DIR/tools/check.sh"; then
	die "static checks failed"
fi

if ! XDG_DATA_HOME="$SB" GAME_DIR="$GAME_DIR" "$FARMER_DIR/install.sh" >"$OUT_DIR/install.log" 2>&1; then
	cat "$OUT_DIR/install.log" >&2
	die "sandbox install failed"
fi
INSTALLED_SHA="$(sha256sum "$SB_DATA/patches/patch_farmer.pck" | cut -d' ' -f1)"
[[ "$INSTALLED_SHA" == "$PCK_SHA" ]] || die "sandbox install hash mismatch"

write_cfg() {
	local name="$1" override="$2" base="${3:-$FARMER_DIR/scenarios/one-run.json}"
	python3 - "$base" "$OUT_DIR/$name.json" "$override" <<'PY'
import json
import sys

base, out, override = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
with open(base, encoding="utf-8") as fh:
    cfg = json.load(fh)
cfg.update(override)
with open(out, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2)
PY
}

reset_profile() {
	local name
	for name in profile.json profile.bak.json profile.run profile.run.farmer_bak; do
		rm -f "$SB_DATA/$name"
		if [[ -f "$SNAP/$name" ]]; then
			cp -a "$SNAP/$name" "$SB_DATA/$name"
		fi
	done
	rm -f \
		"$SB_DATA/farmer_command" \
		"$SB_DATA/farmer_command.claimed" \
		"$SB_DATA/farmer_stop" \
		"$SB_DATA/farmer_status.json" \
		"$SB_DATA/farmer.cfg" \
		"$SB_DATA/farmer.log" \
		"$SB_DATA/farmer.log.prev" \
		"$SB_DATA/farmer.run.lock" \
		"$SB_DATA/farmer_runs.jsonl" \
		"$SB_DATA/farmer_session.json" \
		"$SB_DATA/farmer_supervisor_session" \
		"$SB_DATA/farmer_test_crashed"
}

assert_status() {
	local status="$1" name="$2"
	python3 - "$status" "$name" <<'PY'
import json
import sys

path, name = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as fh:
    d = json.load(fh)
tot = d.get("totals") or {}
last = d.get("last") or {}
err = []


def need(cond, msg):
    if not cond:
        err.append(msg)


need(d.get("phase") == "done", "phase != done")
need(bool(d.get("terminal")), "terminal false")
need(not bool(d.get("failed", False)), "failed true")
need(str(d.get("finish_reason") or "") != "", "finish_reason empty")
need(str(d.get("last_transition") or "") != "", "last_transition empty")
need(int(d.get("heartbeat_seq") or 0) > 0, "heartbeat_seq == 0")
need(str(d.get("run_id") or "") != "", "run_id empty")
if name != "cmd-abort":
    need(int(tot.get("runs") or 0) >= 1, "runs == 0")
if name == "one-run":
    need(int(tot.get("wins") or 0) >= 1, "wins == 0")
    need(bool(last.get("victory")), "last.victory false")
    need(int(last.get("kills") or 0) > 0, "kills == 0")
    need(float(last.get("zeny_gain") or 0) > 0, "zeny_gain == 0")
elif name == "stop":
    need(bool(last), "no last run")
    need(int(last.get("kills") or 0) > 0, "kills == 0")
    need(float(last.get("game_s") or 0) > 0, "game_s == 0")
elif name == "endless":
    need(bool(last.get("victory")), "last.victory false")
    need(bool(last.get("endless")), "last.endless false")
    need(int(last.get("endless_mvps") or 0) >= 1, "endless_mvps == 0")
    need(int(last.get("kills") or 0) > 0, "kills == 0")

print("; ".join(err))
sys.exit(1 if err else 0)
PY
}

assert_failed_status() {
	local status="$1" expected="$2"
	python3 - "$status" "$expected" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    d = json.load(fh)
err = []


def need(cond, msg):
    if not cond:
        err.append(msg)


need(d.get("phase") == "failed", "phase != failed")
need(bool(d.get("terminal")), "terminal false")
need(bool(d.get("failed")), "failed false")
need(str(d.get("finish_reason") or "") == sys.argv[2], "finish_reason != " + sys.argv[2])
need(int(d.get("exit_code") or 0) != 0, "exit_code == 0")
need(str(d.get("last_transition") or "") != "", "last_transition empty")

print("; ".join(err))
sys.exit(1 if err else 0)
PY
}

drive_command() {
	local name="$1"
	shift
	python3 - "$SB_DATA" "$name" "$@" <<'PY'
import json
import subprocess
import sys
import time
from pathlib import Path

data = Path(sys.argv[1])
name = sys.argv[2]
proc = subprocess.Popen(sys.argv[3:])
status_path = data / "farmer_status.json"


def wait_status(phase, predicate=lambda _: True):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            state = json.loads(status_path.read_text())
        except FileNotFoundError:
            pass
        else:
            if state["phase"] == phase and predicate(state):
                return state
            if state["terminal"]:
                break
        time.sleep(0.01)
    raise AssertionError(f"{name}: expected phase {phase!r} was not observed")


def publish(command):
    temp = data / "verify-command.tmp"
    temp.write_text(command + "\n")
    temp.replace(data / "farmer_command")


try:
    running = wait_status("run")
    if name == "cmd-abort-settled":
        settled = wait_status("keep")
        assert settled["run_id"] == running["run_id"]
        publish("abort")
    elif name == "cmd-pause-resume":
        publish("pause")
        paused = wait_status("paused")
        assert not paused["terminal"] and paused["totals"]["runs"] == 1
        assert paused["run_id"] == running["run_id"]
        still_paused = wait_status("paused", lambda d: d["heartbeat_seq"] > paused["heartbeat_seq"])
        assert still_paused["totals"]["started"] == 1
        publish("resume")
        resumed = wait_status("run", lambda d: d["run_id"] != running["run_id"])
        assert resumed["pid"] == still_paused["pid"] == running["pid"]
        print(f"paused heartbeat {paused['heartbeat_seq']} -> {still_paused['heartbeat_seq']}; "
              f"resumed in pid {resumed['pid']}", flush=True)
    elif name == "cmd-legacy":
        (data / "farmer_stop").touch()
    else:
        publish(name.removeprefix("cmd-"))
except AssertionError as error:
    print(error, file=sys.stderr, flush=True)
    proc.wait()  # the surrounding timeout still bounds the launcher
    sys.exit(1)
sys.exit(proc.wait())
PY
}

assert_command_status() {
	local status="$1" name="$2" farmer_log="$3"
	python3 - "$status" "$name" "$farmer_log" "$SB_DATA" <<'PY'
import json
import sys
from pathlib import Path

status, name, log, data = sys.argv[1:]
data = Path(data)
d = json.loads(Path(status).read_text())
log = Path(log).read_text()
checkpoint = json.loads((data / "farmer_session.json").read_text())
journal = data / "farmer_runs.jsonl"
rows = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
rows = [r for r in rows if r["session"] == d["session"]]
abort = name.startswith("cmd-abort")
paused = name == "cmd-pause-resume"
started = 2 if paused else 1
lost = int(name == "cmd-abort")
assert d["finish_reason"] == ("abort" if abort else "max_runs" if paused else "finish"), d
assert d["exit_code"] == 0
assert checkpoint["phase"] == "idle" and checkpoint["session"] == d["session"]
assert checkpoint["totals"] == d["totals"]
assert (d["totals"]["started"], d["totals"]["runs"], d["totals"]["lost"]) == (started, started - lost, lost)
assert [r["run_id"] for r in rows] == [f"{d['session']}-r{i}" for i in range(1, started - lost + 1)]
assert d["totals"]["zeny"] == sum(r["zeny_gain"] for r in rows)
assert all(not (data / f).exists() for f in ("farmer_command", "farmer_command.claimed", "farmer_stop"))
assert log.count(" SETTLE ") == started - lost
if abort:
    assert " KEEP_DONE " not in log and " MAINT " not in log
    assert all(not r["kept"] for r in rows)
else:
    assert log.count(" KEEP_DONE ") == log.count(" MAINT ") == started
    reason = "run_timeout" if paused else "finish"
    assert all(r["force_reason"] == reason for r in rows)
PY
}

write_result() {
	local status="$1" name="$2" verdict="$3" rc="$4" reason="$5"
	python3 - "$status" "$name" "$verdict" "$rc" "$reason" "$OUT_DIR/$name.result.json" <<'PY'
import json
import os
import sys

status, name, verdict, rc, reason, out = sys.argv[1:7]
d = {}
if os.path.isfile(status):
    with open(status, encoding="utf-8") as fh:
        d = json.load(fh)
tot = d.get("totals") or {}
last = d.get("last") or {}
row = {
    "scenario": name,
    "verdict": verdict,
    "exit": int(rc),
    "reason": reason,
    "phase": d.get("phase"),
    "terminal": d.get("terminal"),
    "failed": d.get("failed"),
    "finish_reason": d.get("finish_reason"),
    "exit_code": d.get("exit_code"),
    "run_id": d.get("run_id"),
    "heartbeat_seq": d.get("heartbeat_seq"),
    "runs": tot.get("runs"),
    "wins": tot.get("wins"),
    "losses": tot.get("losses"),
    "kills": tot.get("kills"),
    "zeny": tot.get("zeny"),
    "last": {
        k: last.get(k)
        for k in ("victory", "endless", "endless_mvps", "kills", "zeny_gain",
                  "xp_gain", "cards_gain", "kept", "game_s", "wall_s")
    },
    "build": d.get("build"),
}
with open(out, "w", encoding="utf-8") as fh:
    json.dump(row, fh, indent=2, ensure_ascii=False)
PY
}

run_scenario() {
	# expect_fail: the expected terminal finish_reason of a failing launch; empty = clean finish.
	local name="$1" cfg="$2" timeout_s="$3" marker="$4" expect_fail="${5:-}" extra_env="${6:-}"
	local run_log="$OUT_DIR/$name.run.log"
	local status="$OUT_DIR/$name.status.json"
	local farmer_log="$OUT_DIR/$name.farmer.log"
	local reason="" rc=0 verdict=FAIL

	reset_profile
	echo "=== $name (timeout ${timeout_s}s) ==="
	if [[ "$name" == checkpoint-corrupt ]]; then
		printf '{"session": "verify-%s-%s", "phase": "sett' "$name" "$STAMP" >"$SB_DATA/farmer_session.json"
	fi
	set +e
	local env_args=("XDG_DATA_HOME=$SB" "GAME_DIR=$GAME_DIR")
	if [[ "$name" == cmd-* || "$name" == flush-fail || "$name" == checkpoint-corrupt ]]; then
		env_args+=("FARMER_SESSION_ID=verify-$name-$STAMP")
	fi
	if [[ -n "$extra_env" ]]; then
		env_args+=("$extra_env")
	fi
	local launch=(env "${env_args[@]}" timeout --foreground -k 15 "$timeout_s" "$FARMER_DIR/run.sh" "$cfg")
	if [[ "$name" == cmd-* ]]; then
		drive_command "$name" "${launch[@]}" >"$run_log" 2>&1
	else
		"${launch[@]}" >"$run_log" 2>&1
	fi
	rc=$?
	set -e

	if [[ -f "$SB_DATA/farmer_status.json" ]]; then
		cp "$SB_DATA/farmer_status.json" "$status"
	fi
	if [[ -f "$SB_DATA/farmer.log" ]]; then
		cp "$SB_DATA/farmer.log" "$farmer_log"
	fi

	if [[ -n "$expect_fail" ]]; then
		if [[ "$rc" -ne 1 ]]; then
			reason="run.sh exit $rc (expected 1)"
		fi
	elif [[ "$rc" -ne 0 ]]; then
		reason="run.sh exit $rc"
	fi
	if [[ -z "$reason" && ! -f "$status" ]]; then
		reason="no farmer_status.json"
	fi
	if [[ -z "$reason" ]]; then
		local err
		if [[ -n "$expect_fail" ]]; then
			if ! err="$(assert_failed_status "$status" "$expect_fail")"; then
				reason="status: $err"
			fi
		elif ! err="$(assert_status "$status" "$name")"; then
			reason="status: $err"
		fi
		if [[ -z "$reason" && "$name" == checkpoint-corrupt ]] &&
			! cmp -s "$SB_DATA/profile.json" "$SNAP/profile.json"; then
			reason="profile changed although the session could not start"
		fi
	fi
	if [[ -z "$reason" ]]; then
		if [[ ! -f "$farmer_log" ]]; then
			reason="no farmer.log"
		elif ! grep -Fq -- "$marker" "$farmer_log"; then
			reason="missing log marker: $marker"
		elif [[ "$name" == cmd-* ]] && ! assert_command_status "$status" "$name" "$farmer_log" \
			>"$OUT_DIR/$name.assert.log" 2>&1; then
			reason="command status/journal (see $name.assert.log)"
		fi
	fi
	if [[ -z "$reason" ]] && grep -Eq 'SCRIPT ERROR|Parse Error|Invalid call|Cannot call method' "$run_log"; then
		reason="script error in game log"
	fi

	if [[ -z "$reason" ]]; then
		verdict=PASS
		echo "  PASS"
	else
		FAILED=1
		echo "  FAIL: $reason" >&2
	fi
	write_result "$status" "$name" "$verdict" "$rc" "$reason"

	if pgrep -f 'MidgardSurvivors\.x86_64' >/dev/null 2>&1; then
		echo "verify: game process still running after $name; close it and re-run" >&2
		FAILED=1
		return 1
	fi
	return 0
}

assert_recovered() {
	local status="$1" point="$2" session="$3" boot_log="$4"
	python3 - "$status" "$point" "$session" "$SB_DATA/farmer_runs.jsonl" "$boot_log" <<'PY'
import json
import re
import sys
from collections import Counter

path, point, session, journal, boot_log = sys.argv[1:6]
with open(path, encoding="utf-8") as fh:
    d = json.load(fh)
tot = d.get("totals") or {}
rows = []
with open(journal, encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if line:
            row = json.loads(line)
            if row.get("session") == session:
                rows.append(row)
ids = Counter(r.get("run_id") for r in rows)
err = []


def need(cond, msg):
    if not cond:
        err.append(msg)


need(d.get("phase") == "done" and not d.get("failed"), "phase != done")
need(d.get("session") == session, "session id not continued")
need(all(n == 1 for n in ids.values()), "duplicate journal run_id: %s" % dict(ids))
need(int(tot.get("runs") or 0) == len(rows), "totals.runs %s != journal %d" % (tot.get("runs"), len(rows)))
need(int(tot.get("zeny") or 0) == sum(int(r.get("zeny_gain") or 0) for r in rows),
     "totals.zeny != journal zeny_gain sum")
need(int(tot.get("started") or 0) == 2, "totals.started %s != 2" % tot.get("started"))
# Independent of the journal: the profile's zeny moved exactly by the
# accounted gains (the one-run config spends nothing in maintenance).
with open(boot_log, encoding="utf-8") as fh:
    boot = re.search(r" BOOT .* zeny=(\d+)", fh.read())
need(boot is not None, "no BOOT zeny in the crash launch log")
if boot:
    moved = int((d.get("profile") or {}).get("zeny") or 0) - int(boot.group(1))
    need(moved == int(tot.get("zeny") or 0), "profile zeny moved %d != totals.zeny %s" % (moved, tot.get("zeny")))
if point == "run":
    need(int(tot.get("lost") or 0) == 1, "totals.lost %s != 1" % tot.get("lost"))
    need(set(ids) == {session + "-r2"}, "journal ids %s" % sorted(ids))
else:
    need(int(tot.get("lost") or 0) == 0, "totals.lost %s != 0" % tot.get("lost"))
    need(set(ids) == {session + "-r1", session + "-r2"}, "journal ids %s" % sorted(ids))

print("; ".join(err))
sys.exit(1 if err else 0)
PY
}

# Prints and records the verdict; fails (return 1) when the game outlived the scenario.
conclude_scenario() {
	local name="$1" status="$2" rc="$3" reason="$4" verdict=PASS
	if [[ -z "$reason" ]]; then
		echo "  PASS"
	else
		verdict=FAIL
		FAILED=1
		echo "  FAIL: $reason" >&2
	fi
	write_result "$status" "$name" "$verdict" "$rc" "$reason" || FAILED=1
	if pgrep -f 'MidgardSurvivors\.x86_64' >/dev/null 2>&1; then
		echo "verify: game process still running after $name; close it and re-run" >&2
		FAILED=1
		return 1
	fi
}

# Launch 1 is killed at a checkpoint boundary; launch 2 continues the same
# session (as the supervisor would) and must finish cleanly.
run_crash_scenario() {
	local name="$1" cfg="$2" point="$3" marker="$4" timeout_s="$5"
	local session="verify-$name-$STAMP"
	local crash_log="$OUT_DIR/$name.crash.log"
	local run_log="$OUT_DIR/$name.run.log"
	local status="$OUT_DIR/$name.status.json"
	local farmer_log="$OUT_DIR/$name.farmer.log"
	local reason="" rc=0 crash_rc=0 err

	reset_profile
	echo "=== $name (crash at $point, timeout ${timeout_s}s per launch) ==="
	set +e
	env XDG_DATA_HOME="$SB" GAME_DIR="$GAME_DIR" FARMER_SESSION_ID="$session" FARMER_TEST_CRASH_AT="$point" \
		timeout --foreground -k 15 "$timeout_s" "$FARMER_DIR/run.sh" "$cfg" >"$crash_log" 2>&1
	crash_rc=$?
	cp "$SB_DATA/farmer.log" "$OUT_DIR/$name.crash.farmer.log" 2>/dev/null
	env XDG_DATA_HOME="$SB" GAME_DIR="$GAME_DIR" FARMER_SESSION_ID="$session" \
		timeout --foreground -k 15 "$timeout_s" "$FARMER_DIR/run.sh" "$cfg" >"$run_log" 2>&1
	rc=$?
	set -e
	cp "$SB_DATA/farmer_status.json" "$status" 2>/dev/null || true
	cp "$SB_DATA/farmer.log" "$farmer_log" 2>/dev/null || true

	if [[ "$crash_rc" -eq 0 || "$crash_rc" -eq 124 ]]; then
		reason="crash launch exit $crash_rc (expected a killed farmer)"
	elif ! grep -Fq -- "TEST_CRASH $point" "$OUT_DIR/$name.crash.farmer.log" 2>/dev/null; then
		reason="crash launch did not reach $point"
	elif [[ "$rc" -ne 0 ]]; then
		reason="recovery run.sh exit $rc"
	elif [[ ! -f "$status" ]]; then
		reason="no farmer_status.json"
	elif ! err="$(assert_recovered "$status" "$point" "$session" "$OUT_DIR/$name.crash.farmer.log")"; then
		reason="status: $err"
	elif ! grep -Fq -- "$marker" "$farmer_log"; then
		reason="missing log marker: $marker"
	elif grep -Eq 'SCRIPT ERROR|Parse Error|Invalid call|Cannot call method' "$crash_log" "$run_log"; then
		reason="script error in game log"
	fi

	conclude_scenario "$name" "$status" "$rc" "$reason"
}

# The real supervisor owns the session (its id is pre-seeded so FARMER_TEST_*
# hooks answer). Attempt 1 is SIGKILLed at point; attempt 2 must continue the
# same session and account every settled run exactly once.
run_supervised_scenario() {
	local name="$1" cfg="$2" point="$3" marker="$4" timeout_s="$5"
	local session="verify-$name-$STAMP"
	local run_log="$OUT_DIR/$name.run.log"
	local status="$OUT_DIR/$name.status.json"
	local farmer_log="$OUT_DIR/$name.farmer.log"
	local boot_log="$OUT_DIR/$name.crash.farmer.log"
	local reason="" rc=0 err mode=wait
	local env_args=("XDG_DATA_HOME=$SB" "GAME_DIR=$GAME_DIR")

	reset_profile
	echo "=== $name (SIGKILL at $point under the supervisor, timeout ${timeout_s}s) ==="
	printf '%s\n' "$session" >"$SB_DATA/farmer_supervisor_session"
	if [[ "$point" == run ]]; then
		mode=kill-run
	else
		env_args+=("FARMER_TEST_CRASH_AT=$point")
	fi
	set +e
	env "${env_args[@]}" timeout --foreground -k 30 "$timeout_s" \
		python3 "$FARMER_DIR/tools/drive_supervisor.py" "$SB_DATA" "$mode" "$OUT_DIR/$name" -- \
		python3 "$FARMER_DIR/tools/supervisor.py" "$cfg" >"$run_log" 2>&1
	rc=$?
	set -e
	cp "$SB_DATA/farmer_status.json" "$status" 2>/dev/null || true
	cp "$SB_DATA/farmer.log" "$farmer_log" 2>/dev/null || true
	cp "$SB_DATA/farmer.log.prev" "$boot_log" 2>/dev/null || true

	if [[ "$rc" -ne 0 ]]; then
		reason="supervised launch exit $rc"
	elif [[ "$mode" == kill-run ]] && ! grep -q '^drive: SIGKILL game pid .* in run .*-r1$' "$run_log"; then
		reason="the game was not killed in run r1"
	elif [[ "$mode" == wait ]] && ! grep -Fq -- "TEST_CRASH $point" "$boot_log" 2>/dev/null; then
		reason="attempt 1 did not crash at $point"
	elif ! grep -q 'attempt 1: failed' "$run_log" || ! grep -q 'attempt 2: finished' "$run_log"; then
		reason="supervisor did not fail attempt 1 and finish attempt 2"
	elif [[ ! -f "$status" || ! -f "$boot_log" ]]; then
		reason="no farmer_status.json or attempt-1 farmer.log"
	elif ! err="$(assert_recovered "$status" "$point" "$session" "$boot_log")"; then
		reason="status: $err"
	elif ! grep -Fq -- "$marker" "$farmer_log"; then
		reason="missing log marker: $marker"
	elif grep -Eq 'SCRIPT ERROR|Parse Error|Invalid call|Cannot call method' "$run_log"; then
		reason="script error in game log"
	fi

	conclude_scenario "$name" "$status" "$rc" "$reason"
}

run_soak() {
	local hours="$1"
	local session="verify-soak-$STAMP"
	local run_log="$OUT_DIR/soak.run.log"
	local status="$OUT_DIR/soak.status.json"
	local reason="" rc=0
	local minutes deadline
	minutes="$(python3 -c 'import sys; print(float(sys.argv[1]) * 60)' "$hours")"
	deadline="$(python3 -c 'import sys; print(int(float(sys.argv[1]) * 3600) + 1800)' "$hours")"
	write_cfg soak "{\"max_minutes\":$minutes,\"max_runs\":0,\"hard_exit\":true,\"display\":false}" "$SOAK_STRATEGY"

	reset_profile
	echo "=== soak (${hours} h of $(basename "$SOAK_STRATEGY"), deadline ${deadline}s) ==="
	printf '%s\n' "$session" >"$SB_DATA/farmer_supervisor_session"
	set +e
	env XDG_DATA_HOME="$SB" GAME_DIR="$GAME_DIR" timeout --foreground -k 120 "$deadline" \
		python3 "$FARMER_DIR/tools/drive_supervisor.py" "$SB_DATA" sample "$OUT_DIR/soak" -- \
		python3 "$FARMER_DIR/tools/supervisor.py" "$OUT_DIR/soak.json" >"$run_log" 2>&1
	rc=$?
	set -e
	cp "$SB_DATA/farmer_status.json" "$status" 2>/dev/null || true
	cp "$SB_DATA/farmer_runs.jsonl" "$OUT_DIR/soak.journal.jsonl" 2>/dev/null || true
	cp "$SB_DATA/farmer.log" "$OUT_DIR/soak.farmer.log" 2>/dev/null || true

	if [[ "$rc" -eq 124 ]]; then
		reason="soak overran max_minutes by more than 30 min"
	elif ! python3 "$FARMER_DIR/tools/soak_check.py" "$OUT_DIR/soak.samples.jsonl" \
		"$OUT_DIR/soak.journal.jsonl" "$status" --session "$session" --supervisor-exit "$rc" \
		--min-hours "$hours" >"$OUT_DIR/soak.verdict.log" 2>&1; then
		reason="soak_check (see soak.verdict.log)"
	fi
	cat "$OUT_DIR/soak.verdict.log" 2>/dev/null || true

	conclude_scenario soak "$status" "$rc" "$reason"
}

write_cfg one-run '{"speed":10.0,"max_runs":1,"hard_exit":true,"endless":false,"display":false}'
write_cfg stop '{"class":"thief","max_minutes":1.0,"stall_seconds":10.0,"max_runs":0,"speed":10.0,"hard_exit":true,"endless":false,"display":false}'
write_cfg endless '{"speed":10.0,"max_runs":1,"endless":true,"endless_minutes":1.0,"endless_mvps":2,"hard_exit":true,"display":false}'
write_cfg flush-fail '{"speed":10.0,"max_runs":1,"run_minutes":0.2,"max_minutes":0.5,"stall_seconds":10.0,"hard_exit":true,"endless":false,"display":false}'
# Short forced runs: settlement and keep still happen, a run takes seconds.
write_cfg crash-run '{"speed":10.0,"max_runs":1,"run_minutes":0.2,"stall_seconds":10.0,"hard_exit":true,"endless":false,"display":false}'
write_cfg crash-settled '{"speed":10.0,"max_runs":2,"run_minutes":0.2,"stall_seconds":10.0,"hard_exit":true,"endless":false,"display":false}'
write_cfg commands '{"speed":10.0,"max_runs":2,"run_minutes":0.2,"stall_seconds":10.0,"hard_exit":true,"endless":false,"display":false}'

for scenario in "${SCENARIOS[@]}"; do
	case "$scenario" in
		one-run) run_scenario one-run "$OUT_DIR/one-run.json" 300 FINISH || break ;;
		stop) run_scenario stop "$OUT_DIR/stop.json" 180 'STOP max_minutes' || break ;;
		endless) run_scenario endless "$OUT_DIR/endless.json" 360 ENDLESS_DONE || break ;;
		flush-fail) run_scenario flush-fail "$OUT_DIR/flush-fail.json" 180 'FAIL flush_failed' flush_failed "FARMER_TEST_FLUSH_FAIL=1" || break ;;
		checkpoint-corrupt) run_scenario checkpoint-corrupt "$OUT_DIR/crash-run.json" 120 'FAIL checkpoint_corrupt' checkpoint_corrupt || break ;;
		crash-run) run_crash_scenario crash-run "$OUT_DIR/crash-run.json" run 'RUN_LOST' 180 || break ;;
		crash-settled) run_crash_scenario crash-settled "$OUT_DIR/crash-settled.json" settled 'journal=appended' 180 || break ;;
		crash-journaled) run_crash_scenario crash-journaled "$OUT_DIR/crash-settled.json" journaled 'journal=present' 180 || break ;;
		cmd-abort-settled) run_scenario "$scenario" "$OUT_DIR/commands.json" 75 FINISH "" FARMER_TEST_WAIT_AT_KEEP=1 || break ;;
		cmd-*) run_scenario "$scenario" "$OUT_DIR/commands.json" 75 FINISH || break ;;
		supervised-kill-run) run_supervised_scenario "$scenario" "$OUT_DIR/crash-run.json" run 'RUN_LOST' 300 || break ;;
		supervised-crash-settled) run_supervised_scenario "$scenario" "$OUT_DIR/crash-settled.json" settled 'journal=appended' 300 || break ;;
		soak) run_soak "$SOAK_HOURS" || break ;;
	esac
done

python3 - "$OUT_DIR" "$PCK_SHA" <<'PY'
import glob
import json
import os
import sys

out, sha = sys.argv[1], sys.argv[2]
rows = []
for path in sorted(glob.glob(os.path.join(out, "*.result.json"))):
    with open(path, encoding="utf-8") as fh:
        rows.append(json.load(fh))
with open(os.path.join(out, "summary.json"), "w", encoding="utf-8") as fh:
    json.dump({"build_sha256": sha, "rows": rows}, fh, indent=2, ensure_ascii=False)
print()
print("| scenario | result | exit | phase | runs/wins | kills | zeny |")
print("|---|---|---|---|---|---|---|")
for row in rows:
    last = row.get("last") or {}
    print("| %s | %s | %s | %s | %s/%s | %s | %s |" % (
        row.get("scenario"), row.get("verdict"), row.get("exit"),
        row.get("phase") or "-", row.get("runs"), row.get("wins"),
        last.get("kills"), row.get("zeny"),
    ))
PY

if [[ "$FAILED" -ne 0 ]]; then
	echo "verify: FAIL; sandbox kept at $SB" >&2
	exit 1
fi

if [[ "$KEEP" == "1" ]]; then
	echo "verify: PASS; sandbox kept at $SB"
else
	rm -rf "$SB"
	echo "verify: PASS"
fi
}

main "$@"
