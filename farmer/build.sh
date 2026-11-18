#!/usr/bin/env bash
# Build patch_farmer.pck from the installed official patch.
#
# The game's own updater mounts user://patches/<file> from state.json. We build
# a copy of the current official patch with exactly two files added/replaced:
#   scripts/autoload/save.gdc  - official Save + an inert bootstrap hook
#   scripts/core/farmer.gdc    - the farming driver
#
# Requirements: Python 3, curl, unzip, ~500 MB RAM, the game installed.
# GDRE Tools v2.7.4 is downloaded to .build/gdre unless GDRE is set.
set -euo pipefail

FARMER_DIR="$(cd "$(dirname "$0")" && pwd)"
GAME_DIR="${GAME_DIR:-$HOME/games/midgard-survivors}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/godot/app_userdata/Midgard Survivors"
PATCHES="$DATA/patches"
STATE="$PATCHES/state.json"
WORK="$FARMER_DIR/.build"
BYTECODE="${BYTECODE:-ebc36a7}"
OUT="$FARMER_DIR/patch_farmer.pck"
INFO="$FARMER_DIR/patch_farmer.info"
BUILD_JSON="$FARMER_DIR/farmer_build.json"

die() { echo "build: $*" >&2; exit 1; }

[[ -x "$GAME_DIR/MidgardSurvivors.x86_64" ]] || die "game not found at $GAME_DIR"
[[ -f "$STATE" ]] || die "no state.json at $STATE (launch the game once)"
[[ -f "$FARMER_DIR/src/farmer.gd" ]] || die "src/farmer.gd missing"
[[ -f "$FARMER_DIR/src/save_hook.gd" ]] || die "src/save_hook.gd missing"

state_get() {
	python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],""))' "$STATE" "$1"
}

PATCH_FILE="$(state_get file)"
if [[ "$PATCH_FILE" == "patch_farmer.pck" ]]; then
	if [[ -f "$INFO" ]]; then
		PATCH_FILE="$(sed -n 's/^PATCH_FILE=//p' "$INFO")"
	else
		VER="$(state_get version)"
		if [[ -n "$VER" && -f "$PATCHES/patch_$VER.pck" ]]; then
			PATCH_FILE="patch_$VER.pck"
		else
			PATCH_FILE="$(basename "$(ls -1t "$PATCHES"/patch_0.*.pck 2>/dev/null | head -1)")"
		fi
	fi
fi
[[ -n "$PATCH_FILE" ]] || die "state.json has no official patch file"
PATCH_PCK="${PATCH_PCK:-$PATCHES/$PATCH_FILE}"
BRIDGE_FILE="$(python3 -c 'import json,sys
d=json.load(open(sys.argv[1])).get("bridge",{})
print(d.get("file","") if isinstance(d,dict) else "")' "$STATE")"
BRIDGE_PCK="${BRIDGE_PCK:-$PATCHES/$BRIDGE_FILE}"
BASE_PCK="${BASE_PCK:-$GAME_DIR/MidgardSurvivors.pck}"

[[ -f "$PATCH_PCK" ]] || die "official patch not found: $PATCH_PCK"
PATCH_SHA="$(sha256sum "$PATCH_PCK" | cut -d' ' -f1)"
BRIDGE_SHA=""
if [[ -n "$BRIDGE_FILE" && -f "$BRIDGE_PCK" ]]; then
	BRIDGE_SHA="$(sha256sum "$BRIDGE_PCK" | cut -d' ' -f1)"
fi

mkdir -p "$WORK"
GDRE="${GDRE:-$WORK/gdre/gdre_tools.x86_64}"
if [[ ! -x "$GDRE" ]]; then
	echo "build: downloading GDRE Tools v2.7.4..."
	mkdir -p "$WORK/gdre"
	curl -fsSL -o "$WORK/gdre.zip" \
		https://github.com/GDRETools/gdsdecomp/releases/download/v2.7.4/GDRE_tools-v2.7.4-linux.zip
	unzip -q -o "$WORK/gdre.zip" -d "$WORK/gdre"
	GDRE="$WORK/gdre/gdre_tools.x86_64"
fi
[[ -x "$GDRE" ]] || die "GDRE not available (set GDRE=/path/to/gdre_tools.x86_64)"

rm -rf "$WORK/extract" "$WORK/src" "$WORK/player_src" "$WORK/out"
mkdir -p "$WORK/extract" "$WORK/src" "$WORK/player_src" "$WORK/out"

extract_script() {
	local pck="$1" label="$2" res="$3" name="$4"
	[[ -f "$pck" ]] || return 1
	"$GDRE" --headless --extract="$pck" --output="$WORK/extract/$label" \
		--include="$res" >/dev/null 2>&1 || true
	local found
	found="$(find "$WORK/extract/$label" -name "$name" -type f 2>/dev/null | head -1)"
	if [[ -n "$found" ]]; then
		cp "$found" "$WORK/extract/$name"
		return 0
	fi
	return 1
}

# Effective script = official patch, else bridge, else base PCK.
extract_effective() {
	local res="$1" name="$2" what="$3"
	if ! extract_script "$PATCH_PCK" patch "$res" "$name"; then
		if ! extract_script "$BRIDGE_PCK" bridge "$res" "$name"; then
			extract_script "$BASE_PCK" base "$res" "$name" || die "$what not found in any pack"
		fi
	fi
}

extract_effective 'res://scripts/autoload/save.gdc' save.gdc 'save.gdc'
extract_effective 'res://scripts/core/player.gdc' player.gdc 'player.gdc'

"$GDRE" --headless --decompile="$WORK/extract/save.gdc" --bytecode="$BYTECODE" \
	--output="$WORK/src" >/dev/null 2>&1
[[ -f "$WORK/src/save.gd" ]] || die "could not decompile save.gdc"

python3 "$FARMER_DIR/tools/inject_hook.py" \
	"$WORK/src/save.gd" "$FARMER_DIR/src/save_hook.gd" "$WORK/src/save_hooked.gd"

"$GDRE" --headless --decompile="$WORK/extract/player.gdc" --bytecode="$BYTECODE" \
	--output="$WORK/player_src" >/dev/null 2>&1
[[ -f "$WORK/player_src/player.gd" ]] || die "could not decompile player.gdc"
python3 "$FARMER_DIR/tools/patch_player.py" \
	"$WORK/player_src/player.gd" "$WORK/player_src/player_patched.gd"

"$GDRE" --headless --compile="$WORK/src/save_hooked.gd" --bytecode="$BYTECODE" \
	--output="$WORK/out" >/dev/null 2>&1
"$GDRE" --headless --compile="$WORK/player_src/player_patched.gd" --bytecode="$BYTECODE" \
	--output="$WORK/out" >/dev/null 2>&1
"$GDRE" --headless --compile="$FARMER_DIR/src/farmer.gd" --bytecode="$BYTECODE" \
	--output="$WORK/out" >/dev/null 2>&1
[[ -f "$WORK/out/save_hooked.gdc" ]] || die "save_hooked.gdc was not compiled"
[[ -f "$WORK/out/player_patched.gdc" ]] || die "player_patched.gdc was not compiled"
[[ -f "$WORK/out/farmer.gdc" ]] || die "farmer.gdc was not compiled"

rm -f "$OUT"
"$GDRE" --headless --pck-patch="$PATCH_PCK" \
	--patch-file="$WORK/out/save_hooked.gdc=res://scripts/autoload/save.gdc" \
	--patch-file="$WORK/out/player_patched.gdc=res://scripts/core/player.gdc" \
	--patch-file="$WORK/out/farmer.gdc=res://scripts/core/farmer.gdc" \
	--output="$OUT" >/dev/null 2>&1
[[ -f "$OUT" ]] || die "PCK patch failed"

"$GDRE" --headless --list-files="$OUT" 2>/dev/null | grep -q 'res://scripts/autoload/save.gdc' \
	|| die "built pck has no save.gdc"
"$GDRE" --headless --list-files="$OUT" 2>/dev/null | grep -q 'res://scripts/core/player.gdc' \
	|| die "built pck has no player.gdc"
"$GDRE" --headless --list-files="$OUT" 2>/dev/null | grep -q 'res://scripts/core/farmer.gdc' \
	|| die "built pck has no farmer.gdc"

OUT_SHA="$(sha256sum "$OUT" | cut -d' ' -f1)"
GAME_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version",""))' "$STATE" 2>/dev/null || true)"
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > "$INFO" <<EOF
PATCH_FILE=$PATCH_FILE
PATCH_VERSION=$GAME_VERSION
PATCH_SHA256=$PATCH_SHA
BRIDGE_FILE=$BRIDGE_FILE
BRIDGE_SHA256=$BRIDGE_SHA
BYTECODE=$BYTECODE
FARMER_API=3
PATCH_FARMER_SHA256=$OUT_SHA
BUILT_AT=$BUILT_AT
EOF

python3 - "$BUILD_JSON" <<PY
import json, sys
json.dump({
    "patch_file": "$PATCH_FILE",
    "game_version": "$GAME_VERSION",
    "patch_sha256": "$PATCH_SHA",
    "farmer_sha256": "$OUT_SHA",
    "bytecode": "$BYTECODE",
    "api": 3,
    "built_at": "$BUILT_AT",
}, open(sys.argv[1], "w"), indent=2)
PY

rm -rf "$WORK/extract" "$WORK/src" "$WORK/out"
echo "Built $OUT"
echo "  base patch: $PATCH_FILE"
echo "  size:       $(du -h "$OUT" | cut -f1)"
echo "  sha256:     $OUT_SHA"
echo "  next:       ./install.sh"
