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
BACKUP_DIR="${FARMER_BACKUP_DIR:-$FARMER_DIR/backups}"
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

if [[ -n "${FARMER_SESSION_ID:-}" ]]; then
	if ! unshare -cn -- true; then
		die "network isolation requires util-linux unshare -cn and permission to create user/network namespaces; no game launched"
	fi
fi

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
BACKUP="$BACKUP_DIR/$STAMP"
PROFILE_FILES=(profile.json profile.bak.json profile.run profile.run.farmer_bak)
mkdir -p -- "$BACKUP"
for name in "${PROFILE_FILES[@]}"; do
	if [[ -f "$DATA/$name" ]]; then cp "$DATA/$name" "$BACKUP/$name"; fi
done
# Only timestamped snapshots participate in routine rotation.
find "$BACKUP_DIR" -regextype posix-extended -mindepth 1 -maxdepth 1 -type d \
	-regex '.*/[0-9]{8}-[0-9]{6}-[0-9]+' -printf '%T@ %p\0' |
	sort -z -nr | tail -zn +11 | cut -z -d ' ' -f2- | xargs -0r rm -rf -- || true

publish_known_good() (
	local dir name
	local -a files=(profile.json)
	for name in "${PROFILE_FILES[@]:1}"; do
		if [[ -e "$DATA/$name" ]]; then files+=("$name"); fi
	done
	for name in "${files[@]}"; do
		[[ -f "$DATA/$name" && -s "$DATA/$name" ]] || exit 1
	done

	dir="$(mktemp -d -- "$BACKUP_DIR/.known-good.XXXXXXXX")" || exit 1
	trap 'rm -rf -- "$dir"' EXIT
	mkdir -- "$dir/snapshot" "$dir/user" || exit 1
	(cd "$DATA" && sha256sum -- "${files[@]}") >"$dir/snapshot/SHA256SUMS" || exit 1
	for name in "${files[@]}"; do
		cp -- "$DATA/$name" "$dir/snapshot/$name" &&
			cp -- "$dir/snapshot/$name" "$dir/user/$name" || exit 1
	done
	# The game stores binary profiles; verify the copy byte for byte.
	# Hashing the second copy checks both the snapshot and copying it back out.
	(cd "$dir/user" && sha256sum --check --status -) <"$dir/snapshot/SHA256SUMS" || exit 1

	if [[ -e "$BACKUP_DIR/known-good" ]]; then
		mv -T --exchange --no-copy -- "$dir/snapshot" "$BACKUP_DIR/known-good"
	else
		mv -T -- "$dir/snapshot" "$BACKUP_DIR/known-good"
	fi
)

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
launch=("$GAME")
if [[ -n "${FARMER_SESSION_ID:-}" ]]; then
	ready="$(mktemp -- "$LOG_DIR/.net-$STAMP.XXXXXXXX")" || die "cannot prepare network isolation launch"
	trap 'rm -f -- "$ready"' EXIT
	# Signal actual namespace entry independently of the game's exit code.
	# No --fork or new session: the game stays in the supervisor's process group.
	launch=(unshare -cn -- "$BASH" -ec 'printf "1\n" >"$1"; shift; exec "$@"' bash "$ready" "$GAME")
fi

set +e
"${launch[@]}" "${args[@]}" 2>&1 | tee "$LOG"
code=${PIPESTATUS[0]}
set -e
if [[ -n "${FARMER_SESSION_ID:-}" && ! -s "$ready" ]]; then
	die "network isolation failed before the supervised game could launch; see $LOG"
fi

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
	if [[ -n "${FARMER_SESSION_ID:-}" && "$finish_reason" =~ ^(finish|stop|max_runs|wins|goal|no_target)$ ]] &&
		! publish_known_good; then
		echo "run: known-good copy verification failed or publication was unavailable; previous snapshot unchanged" >&2
	fi
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
