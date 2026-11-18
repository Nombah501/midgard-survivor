#!/usr/bin/env python3
"""Best-effort static check of game symbols used by src/farmer.gd.

Usage: check_api.py [farmer.gd] [decompiled_src_dir]

This is a maintenance aid, not a proof: it only checks that identifiers used as
`Save.x`, `world.x`, `GameData.x`, `Equipment.x`, `Player.x`, `Menus.x`,
`menus.x`, `raid.x`, `altars.x`, `Bot.x` exist as a func/var/const in the
decompiled 0.2.3 tree. Engine/inherited members are whitelisted.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT.parent / "analysis" / "src"
FARMER = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "src" / "farmer.gd"

TARGETS = {
    "Save": "save.gd",
    "world": "main.gd",
    "GameData": "game_data.gd",
    "Equipment": "equipment.gd",
    "Player": "player.gd",
    "Menus": "menus.gd",
    "menus": "menus.gd",
    "raid": "mvp_raid.gd",
    "altars": "altars.gd",
    "Bot": "bot.gd",
    "Potential": "potential.gd",
}

ENGINE = {"has_method", "get", "set", "call", "get_meta", "set_meta", "remove_meta", "connect", "disconnect"}

WHITELIST = {
    "Save": set(ENGINE),
    "world": set(ENGINE) | {
        "position", "global_position", "rotation", "scale", "name", "get_tree",
        "is_inside_tree", "queue_free", "free", "get", "set", "call", "has_method",
        "connect", "disconnect", "visible", "process_mode", "print_tree",
    },
    "GameData": set(ENGINE),
    "Equipment": set(ENGINE),
    "Player": {"new"},
    "Menus": set(ENGINE),
    "menus": set(ENGINE),
    "raid": set(ENGINE) | {"position", "name"},
    "altars": set(ENGINE) | {"position", "name"},
    "Bot": set(ENGINE),
    "Potential": set(ENGINE),
}


def members(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: set[str] = set()
    for pat in (
        r"^\s*(?:static\s+)?func\s+([A-Za-z_]\w*)",
        r"^\s*var\s+([A-Za-z_]\w*)",
        r"^\s*const\s+([A-Za-z_]\w*)",
        r"^\s*@export(?:_\w+)?\s+var\s+([A-Za-z_]\w*)",
    ):
        out.update(re.findall(pat, text, re.M))
    return out


def main() -> int:
    if not SRC.is_dir():
        print(f"check_api: decompiled source not found: {SRC}", file=sys.stderr)
        return 2
    table = {}
    for name, fn in TARGETS.items():
        p = SRC / fn
        table[name] = members(p) if p.is_file() else set()
    text = FARMER.read_text(encoding="utf-8", errors="replace")
    missing = {}
    for owner, fn in TARGETS.items():
        for m in re.finditer(rf"\b{re.escape(owner)}\.([A-Za-z_]\w*)", text):
            attr = m.group(1)
            if attr in WHITELIST.get(owner, set()):
                continue
            if attr not in table[owner]:
                missing.setdefault(owner, set()).add(attr)
    if not missing:
        print("check_api: OK")
        return 0
    for owner in sorted(missing):
        print(f"{owner}: {', '.join(sorted(missing[owner]))}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
