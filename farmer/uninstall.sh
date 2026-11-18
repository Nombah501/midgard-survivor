#!/usr/bin/env bash
# Restore the official update slot and remove the installed farmer pack.
# The profile, farmer.cfg, logs and backups are kept.
set -euo pipefail

FARMER_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/godot/app_userdata/Midgard Survivors"
PATCHES="$DATA/patches"
STATE="$PATCHES/state.json"
INFO="$FARMER_DIR/patch_farmer.info"

die() { echo "uninstall: $*" >&2; exit 1; }

[[ -f "$STATE" ]] || die "no state.json at $STATE"

if pgrep -f 'MidgardSurvivors.x86_64' >/dev/null 2>&1; then
	die "the game is running; close it first"
fi

CURRENT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("file",""))' "$STATE")"
if [[ "$CURRENT" != "patch_farmer.pck" ]]; then
	echo "uninstall: state.json already points to $CURRENT; nothing to do"
	rm -f "$PATCHES/patch_farmer.pck" "$DATA/farmer_build.json"
	exit 0
fi

PATCH_FILE=""
PATCH_VERSION=""
if [[ -f "$INFO" ]]; then
	PATCH_FILE="$(sed -n 's/^PATCH_FILE=//p' "$INFO")"
	PATCH_VERSION="$(sed -n 's/^PATCH_VERSION=//p' "$INFO")"
fi

if [[ -z "$PATCH_FILE" || ! -f "$PATCHES/$PATCH_FILE" ]]; then
	die "cannot identify the official patch; set PATCH_FILE=... and rerun"
fi

python3 - "$STATE" "$PATCH_FILE" "$PATCH_VERSION" <<'PY'
import json, sys
path, patch_file, version = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(path))
d["file"] = patch_file
d.pop("farmer", None)
if version:
    d["version"] = version
json.dump(d, open(path + ".tmp", "w"), indent="\t", sort_keys=True)
PY
mv -f "$STATE.tmp" "$STATE"

rm -f "$PATCHES/patch_farmer.pck" "$DATA/farmer_build.json"
echo "Restored official patch: $PATCH_FILE"
echo "Kept: profile, farmer.cfg, logs, backups."
