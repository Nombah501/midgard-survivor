#!/usr/bin/env bash
# Run the Midgard Survivors farmer.
#   ./run.sh                         use the current farmer.cfg
#   ./run.sh presets/one-run.json    copy a preset into place, then run
#   FARMER_DISPLAY=1 ./run.sh        windowed instead of headless
set -euo pipefail

FARMER_DIR="$(cd "$(dirname "$0")" && pwd)"
GAME_DIR="${GAME_DIR:-$HOME/games/midgard-survivors}"
GAME="$GAME_DIR/MidgardSurvivors.x86_64"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/godot/app_userdata/Midgard Survivors"
PATCHES="$DATA/patches"
STATE="$PATCHES/state.json"
INFO="$FARMER_DIR/patch_farmer.info"
LOG_DIR="$FARMER_DIR/logs"
STAMP="$(date +%Y%m%d-%H%M%S)-$$"
LOG="$LOG_DIR/run-$STAMP.log"

# Exit 78 (EX_CONFIG): a restart cannot fix this (missing game/patch, stale
# build, bad preset); the supervisor quarantines without retrying.
die() { echo "run: $*" >&2; exit 78; }
# Exit 1: transient, another launcher or game instance is still alive.
busy() { echo "run: $*" >&2; exit 1; }

[[ -x "$GAME" ]] || die "game not found at $GAME"
[[ -f "$STATE" ]] || die "no state.json at $STATE (launch the game once)"
[[ -f "$INFO" ]] || die "patch_farmer.info missing; run ./build.sh && ./install.sh"

# One launcher at a time. The game also checks its own process below.
exec 9>"$DATA/farmer.run.lock"
if ! flock -n 9; then
	busy "another farmer launcher holds the lock"
fi

if pgrep -f 'MidgardSurvivors\.x86_64' >/dev/null 2>&1; then
	busy "the game is already running; close it first"
fi

info_get() { sed -n "s/^$1=//p" "$INFO"; }
PATCH_FILE="$(info_get PATCH_FILE)"
PATCH_SHA="$(info_get PATCH_SHA256)"
FARMER_SHA="$(info_get PATCH_FARMER_SHA256)"
[[ -f "$PATCHES/$PATCH_FILE" ]] || die "official patch missing: $PATCHES/$PATCH_FILE"
[[ -f "$PATCHES/patch_farmer.pck" ]] || die "farmer pack not installed; run ./install.sh"
[[ "$(sha256sum "$PATCHES/$PATCH_FILE" | cut -d' ' -f1)" == "$PATCH_SHA" ]] \
	|| die "official patch changed (game updated); rebuild"
[[ "$(sha256sum "$PATCHES/patch_farmer.pck" | cut -d' ' -f1)" == "$FARMER_SHA" ]] \
	|| die "installed farmer pack is stale; run ./build.sh && ./install.sh"
[[ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("file",""))' "$STATE")" == "patch_farmer.pck" ]] \
	|| die "state.json does not mount patch_farmer.pck; run ./install.sh"

mkdir -p "$LOG_DIR"
if [[ $# -ge 1 ]]; then
	[[ -f "$1" ]] || die "preset not found: $1"
	cp "$1" "$DATA/farmer.cfg"
fi
[[ -f "$DATA/farmer.cfg" ]] || die "no farmer.cfg; pass a preset or create one"

DISPLAY_MODE="$(python3 -c 'import json,sys; print("1" if json.load(open(sys.argv[1])).get("display",False) else "0")' "$DATA/farmer.cfg" 2>/dev/null || echo 0)"
if [[ "${FARMER_DISPLAY:-}" == "1" || "${FARMER_DISPLAY:-}" == "true" ]]; then
	DISPLAY_MODE=1
	python3 - "$DATA/farmer.cfg" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d["display"]=True
json.dump(d, open(p,"w"), indent=2)
PY
fi

# Unique backup; never overwrites a previous snapshot.
BACKUP="$FARMER_DIR/backups/$STAMP"
mkdir -p "$BACKUP"
for name in profile.json profile.bak.json profile.run profile.run.farmer_bak; do
	if [[ -f "$DATA/$name" ]]; then cp "$DATA/$name" "$BACKUP/$name"; fi
done
# Keep the 10 newest routine snapshots; never touch backups/official-state.json.
{ ls -1dt "$FARMER_DIR"/backups/*/ 2>/dev/null || true; } | tail -n +11 | xargs -r rm -rf || true

rm -f "$DATA/farmer_stop" "$DATA/farmer_status.json"
if [[ -f "$DATA/farmer.log" ]]; then
	mv -f "$DATA/farmer.log" "$DATA/farmer.log.prev"
fi

echo "Midgard Survivors farmer"
echo "  config: $DATA/farmer.cfg"
echo "  log:    $LOG"
echo "  status: $DATA/farmer_status.json"
echo "  stop:   touch \"$DATA/farmer_stop\""
echo

trap 'touch "$DATA/farmer_stop" 2>/dev/null || true' INT TERM
export FARMER_SESSION=1
args=()
if [[ "$DISPLAY_MODE" != "1" ]]; then
	args+=(--headless)
fi
# Do not pass user args starting with '--': the game's Updater disables all
# patches when it sees one (updater.gd _enabled). The farmer uses the
# GameData \"karma_test\" meta to keep the run open at the victory point.

set +e
"$GAME" "${args[@]}" 2>&1 | tee "$LOG"
code=${PIPESTATUS[0]}
set -e

phase=""
failed=""
finish_reason=""
exit_code=""
if [[ -f "$DATA/farmer_status.json" ]]; then
	IFS='|' read -r phase failed finish_reason exit_code < <(python3 - "$DATA/farmer_status.json" <<'PY'
import json,sys
try:
    d=json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    d={}
print("%s|%s|%s|%s" % (
    d.get("phase", ""),
    "true" if d.get("failed", False) else "false",
    d.get("finish_reason", ""),
    d.get("exit_code", 0),
))
PY
) || true
fi
# A headless clean finish hard-exits with SIGKILL (137) after a verified flush.
# Only that post-flush code is accepted; any other non-zero child code propagates.
if [[ "$phase" == "done" && "$failed" != "true" && ( "$code" == "0" || "$code" == "137" ) ]]; then
	echo "farmer: finished cleanly (exit $code${finish_reason:+ reason=$finish_reason})"
	[[ -f "$DATA/farmer_status.json" ]] && python3 - "$DATA/farmer_status.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
t=d.get("totals",{})
print("  runs=%s wins=%s losses=%s zeny=%s kills=%s" % (t.get("runs"), t.get("wins"), t.get("losses"), t.get("zeny"), t.get("kills")))
print("  rates: " + json.dumps(d.get("rates",{}), ensure_ascii=False))
PY
	exit 0
fi
echo "run: farmer did not finish cleanly (exit $code phase=$phase reason=$finish_reason failed=$failed)" >&2
if [[ "$exit_code" =~ ^[0-9]+$ && "$exit_code" != "0" ]]; then
	exit "$exit_code"
fi
if [[ "$code" == "0" ]]; then
	exit 1
fi
exit "$code"
