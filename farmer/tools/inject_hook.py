#!/usr/bin/env python3
"""Inject the farmer bootstrap into the decompiled Save autoload.

Usage: inject_hook.py <decompiled_save.gd> <save_hook.gd> <output.gd>
Idempotent. Exits non-zero when the expected anchors are missing (a game update
changed save.gd); rerun build.sh after checking the new script.
"""
import sys

src, hook_path, out = sys.argv[1:4]
text = open(src, encoding="utf-8").read()

if "_farmer_tick" in text:
    open(out, "w", encoding="utf-8").write(text)
    print("Save hook already present")
    sys.exit(0)

var_anchor = "var _timer: = 0.0"
if var_anchor not in text:
    sys.exit("Save hook: 'var _timer: = 0.0' anchor not found")
text = text.replace(
    var_anchor,
    var_anchor
    + "\nvar _farmer: Node = null"
    + "\nvar _farmer_failed: = false",
    1,
)

process_anchor = "func _process(delta: float) -> void :"
if process_anchor not in text:
    sys.exit("Save hook: '_process' anchor not found")
text = text.replace(process_anchor, process_anchor + "\n\t_farmer_tick()", 1)

hook = open(hook_path, encoding="utf-8").read()
text = text.rstrip() + "\n\n\n" + hook
open(out, "w", encoding="utf-8").write(text)
print("Save hook injected")
