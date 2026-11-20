#!/usr/bin/env bash
# Install the built farmer pack into the game's update slot.
# Safe: verifies hashes, backs up state/profile, copies atomically.
set -euo pipefail

# Parsed whole before it runs; safe to edit during an install (see run.sh).
main() {

FARMER_DIR="$(cd "$(dirname "$0")" && pwd)"
GAME_DIR="${GAME_DIR:-$HOME/games/midgard-survivors}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/godot/app_userdata/Midgard Survivors"
PATCHES="$DATA/patches"
STATE="$PATCHES/state.json"
INFO="$FARMER_DIR/patch_farmer.info"
PCK="$FARMER_DIR/patch_farmer.pck"
BUILD_JSON="$FARMER_DIR/farmer_build.json"
BACKUP_DIR="${FARMER_BACKUP_DIR:-$FARMER_DIR/backups}"

die() { echo "install: $*" >&2; exit 1; }

[[ -f "$PCK" ]] || die "patch_farmer.pck missing; run ./build.sh"
[[ -f "$INFO" ]] || die "patch_farmer.info missing; run ./build.sh"
[[ -f "$STATE" ]] || die "no state.json at $STATE"
[[ -x "$GAME_DIR/MidgardSurvivors.x86_64" ]] || die "game not found at $GAME_DIR"

if pgrep -f 'MidgardSurvivors\.x86_64' >/dev/null 2>&1; then
	die "the game is running; close it first"
fi

info_get() { sed -n "s/^$1=//p" "$INFO"; }
PATCH_FILE="$(info_get PATCH_FILE)"
PATCH_SHA="$(info_get PATCH_SHA256)"
FARMER_SHA="$(info_get PATCH_FARMER_SHA256)"
[[ -n "$PATCH_FILE" && -n "$PATCH_SHA" && -n "$FARMER_SHA" ]] || die "incomplete patch_farmer.info"
[[ -f "$PATCHES/$PATCH_FILE" ]] || die "official patch missing: $PATCHES/$PATCH_FILE"

OFFICIAL_SHA="$(sha256sum "$PATCHES/$PATCH_FILE" | cut -d' ' -f1)"
[[ "$OFFICIAL_SHA" == "$PATCH_SHA" ]] \
	|| die "official patch changed (game updated); rebuild with ./build.sh"
# If the updater already mounted a newer official patch, do not overwrite it
# with a pack built from an older base.
STATE_OFFICIAL="$(python3 -c 'import json,sys; f=json.load(open(sys.argv[1])).get("file",""); print("" if f=="patch_farmer.pck" else f)' "$STATE")"
if [[ -n "$STATE_OFFICIAL" && "$STATE_OFFICIAL" != "$PATCH_FILE" ]]; then
	die "state.json now mounts $STATE_OFFICIAL, but this pack was built from $PATCH_FILE; rebuild with ./build.sh"
fi

LOCAL_SHA="$(sha256sum "$PCK" | cut -d' ' -f1)"
[[ "$LOCAL_SHA" == "$FARMER_SHA" ]] || die "patch_farmer.pck does not match its manifest"

STAMP="$(date +%Y%m%d-%H%M%S)-$$"
BACKUP="$BACKUP_DIR/$STAMP"
mkdir -p -- "$BACKUP"
for name in state.json profile.json profile.bak.json profile.run profile.run.farmer_bak; do
	if [[ -f "$DATA/$name" ]]; then
		cp "$DATA/$name" "$BACKUP/$name"
	elif [[ -f "$PATCHES/$name" ]]; then
		cp "$PATCHES/$name" "$BACKUP/$name"
	fi
done

# Keep one permanent pre-farmer state snapshot (only if it is official).
if [[ ! -f "$BACKUP_DIR/official-state.json" ]]; then
	if [[ "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("file",""))' "$STATE")" != "patch_farmer.pck" ]]; then
		cp "$STATE" "$BACKUP_DIR/official-state.json"
	fi
fi

cp "$PCK" "$PATCHES/patch_farmer.pck.tmp"
mv -f "$PATCHES/patch_farmer.pck.tmp" "$PATCHES/patch_farmer.pck"
cp "$BUILD_JSON" "$DATA/farmer_build.json"

python3 - "$STATE" "$PATCH_FILE" <<'PY'
import json, sys
path, patch_file = sys.argv[1], sys.argv[2]
d = json.load(open(path))
d["file"] = "patch_farmer.pck"
d["farmer"] = 1
# version stays the official game version
json.dump(d, open(path + ".tmp", "w"), indent="\t", sort_keys=True)
PY
mv -f "$STATE.tmp" "$STATE"

INSTALLED_SHA="$(sha256sum "$PATCHES/patch_farmer.pck" | cut -d' ' -f1)"
[[ "$INSTALLED_SHA" == "$FARMER_SHA" ]] || die "installed pack hash mismatch"

echo "Installed $PATCHES/patch_farmer.pck"
echo "  official: $PATCH_FILE"
echo "  backup:   $BACKUP"
echo "  next:     ./run.sh scenarios/one-run.json"
}

main "$@"
