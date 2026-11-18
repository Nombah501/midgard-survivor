#!/usr/bin/env python3
"""Force the configured job path during a farmer session.

The game's job-change menu (auto_pick) calls `Player.next_job()`
with a random path. The farmer cannot win that same-frame race by polling, so
this tiny seam reads `Save` meta `farmer_job_paths` when it exists. Normal play
(no meta) is byte-for-byte the original behavior.

Usage: patch_player.py <decompiled player.gd> <output.gd>
"""
import sys

src, out = sys.argv[1:3]
text = open(src, encoding="utf-8").read()

if 'Save.has_meta("farmer_job_paths")' in text:
    open(out, "w", encoding="utf-8").write(text)
    print("Player job patch already present")
    sys.exit(0)

anchor = '''func next_job(path: = 0) -> Dictionary:
\tvar paths: = GameData.job_paths(class_id)
\tvar job: Dictionary = paths[clampi(path, 0, paths.size() - 1)].duplicate()'''
if anchor not in text:
    sys.exit("Player patch: next_job anchor not found")

replacement = '''func next_job(path: = 0) -> Dictionary:
\tvar paths: = GameData.job_paths(class_id)
\tvar _farmer_path: = path
\tif Save.has_meta("farmer_job_paths"):
\t\tvar _farmer_paths = Save.get_meta("farmer_job_paths", {})
\t\tif _farmer_paths is Dictionary and _farmer_paths.has(class_id):
\t\t\t_farmer_path = int(_farmer_paths[class_id])
\tvar job: Dictionary = paths[clampi(_farmer_path, 0, paths.size() - 1)].duplicate()'''
text = text.replace(anchor, replacement, 1)

open(out, "w", encoding="utf-8").write(text)
print("Player job patch injected")
