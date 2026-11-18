#!/usr/bin/env bash
# Bounded end-to-end verification of the farmer.
#
# Runs one or more scenarios against a throwaway copy of the real user://
# profile. The real profile is only read. Each scenario has its own timeout;
# a timeout, a non-zero exit, a missing status, or a failed assertion is FAIL.
#
# Usage: ./tools/verify.sh [--one-run] [--stop] [--endless] [--all] [--keep]
# Default: --all.
#
# Artifacts: farmer/logs/verify-<stamp>/{summary.json,*.log,*.status.json}
set -euo pipefail

FARMER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$(cd "$FARMER_DIR/.." && pwd)"
GAME_DIR="${GAME_DIR:-$HOME/games/midgard-survivors}"
REAL_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/godot/app_userdata/Midgard Survivors"
INFO="$FARMER_DIR/patch_farmer.info"
PCK="$FARMER_DIR/patch_farmer.pck"
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
OUT_DIR="$FARMER_DIR/logs/verify-$STAMP"
SB="${VERIFY_SANDBOX:-$REPO_DIR/.sandbox/verify-$STAMP}"
SB_DATA="$SB/godot/app_userdata/Midgard Survivors"
SNAP="$SB/snapshot"
KEEP=0
FAILED=0
SCENARIOS=()

usage() {
	sed -n '2,14p' "$0"
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
		--all) SCENARIOS=(one-run stop endless) ;;
		--keep) KEEP=1 ;;
		-h|--help) usage; exit 0 ;;
		*) die "unknown argument: $arg" ;;
	esac
done
if [[ ${#SCENARIOS[@]} -eq 0 ]]; then
	SCENARIOS=(one-run stop endless)
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
	local name="$1" override="$2"
	python3 - "$FARMER_DIR/presets/one-run.json" "$OUT_DIR/$name.json" "$override" <<'PY'
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
		"$SB_DATA/farmer_stop" \
		"$SB_DATA/farmer_status.json" \
		"$SB_DATA/farmer.cfg" \
		"$SB_DATA/farmer.log" \
		"$SB_DATA/farmer.log.prev" \
		"$SB_DATA/farmer.run.lock"
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
	local name="$1" cfg="$2" timeout_s="$3" marker="$4"
	local run_log="$OUT_DIR/$name.run.log"
	local status="$OUT_DIR/$name.status.json"
	local farmer_log="$OUT_DIR/$name.farmer.log"
	local reason="" rc=0 verdict=FAIL

	reset_profile
	echo "=== $name (timeout ${timeout_s}s) ==="
	set +e
	XDG_DATA_HOME="$SB" GAME_DIR="$GAME_DIR" timeout --foreground -k 15 "$timeout_s" \
		"$FARMER_DIR/run.sh" "$cfg" >"$run_log" 2>&1
	rc=$?
	set -e

	if [[ -f "$SB_DATA/farmer_status.json" ]]; then
		cp "$SB_DATA/farmer_status.json" "$status"
	fi
	if [[ -f "$SB_DATA/farmer.log" ]]; then
		cp "$SB_DATA/farmer.log" "$farmer_log"
	fi

	if [[ "$rc" -ne 0 ]]; then
		reason="run.sh exit $rc"
	fi
	if [[ -z "$reason" && ! -f "$status" ]]; then
		reason="no farmer_status.json"
	fi
	if [[ -z "$reason" ]]; then
		local err
		if ! err="$(assert_status "$status" "$name")"; then
			reason="status: $err"
		fi
	fi
	if [[ -z "$reason" ]]; then
		if [[ ! -f "$farmer_log" ]]; then
			reason="no farmer.log"
		elif ! grep -Fq -- "$marker" "$farmer_log"; then
			reason="missing log marker: $marker"
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

write_cfg one-run '{"speed":10.0,"max_runs":1,"hard_exit":true,"endless":false,"display":false}'
write_cfg stop '{"class":"thief","max_minutes":1.0,"stall_seconds":10.0,"max_runs":0,"speed":10.0,"hard_exit":true,"endless":false,"display":false}'
write_cfg endless '{"speed":10.0,"max_runs":1,"endless":true,"endless_minutes":1.0,"endless_mvps":2,"hard_exit":true,"display":false}'

for scenario in "${SCENARIOS[@]}"; do
	case "$scenario" in
		one-run) run_scenario one-run "$OUT_DIR/one-run.json" 300 FINISH || break ;;
		stop) run_scenario stop "$OUT_DIR/stop.json" 180 'STOP max_minutes' || break ;;
		endless) run_scenario endless "$OUT_DIR/endless.json" 360 ENDLESS_DONE || break ;;
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
