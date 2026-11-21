#!/usr/bin/env python3
"""Instrument native job selection and lethal hits during a farmer session.

The job menu can call next_job() before the farmer can poll it. Likewise,
revivals resolve inside take_damage(), so polling loses the lethal hit cause.
Vanilla play has neither the Save job-path override nor a fall listener.

Usage: patch_player.py <decompiled player.gd> <output.gd>
"""
import sys

src, out = sys.argv[1:3]
text = open(src, encoding="utf-8").read()


def replace_once(source, anchor, replacement):
    if source.count(anchor) != 1:
        sys.exit(f"Player patch: {anchor.strip()} anchor not found")
    return source.replace(anchor, replacement, 1)


def patch_falls(branch, indent, piercing, *, encore=False):
    emit = f"farmer_fell.emit(death_by, {piercing}, revives)"
    after = ["_kaizel(world)", "_revive(world)", "Uniques.try_ankh(world, self):"]
    if encore:
        after.append("world.encore.siegfried_save(world, self):")
    for anchor in after:
        end = "\n" + indent + "\treturn"
        branch = replace_once(branch, anchor + end, anchor + "\n" + indent + "\t" + emit + end)
    return replace_once(branch, f"\n{indent}died.emit()", f"\n{indent}{emit}\n{indent}died.emit()")


fall_signal = "signal farmer_fell(cause: Dictionary, piercing: bool, revives_left: int)\n"
if fall_signal not in text:
    damage, doom, revive = (
        "\nfunc take_damage(", "\nfunc _doom_fall(", "\nfunc _revive(",
    )
    for anchor in (damage, doom, revive):
        if text.count(anchor) != 1:
            sys.exit(f"Player patch: {anchor.strip()} anchor not found")
    text = replace_once(text, "signal died\n", "signal died\n" + fall_signal)
    before, damage_body = text.split(damage)
    damage_body, doom_body = damage_body.split(doom)
    doom_body, rest = doom_body.split(revive)
    text = (before + damage + patch_falls(damage_body, "\t\t", "pierce", encore=True)
            + doom + patch_falls(doom_body, "\t", "true") + revive + rest)

anchor = '''func next_job(path: = 0) -> Dictionary:
\tvar paths: = GameData.job_paths(class_id)
\tvar job: Dictionary = paths[clampi(path, 0, paths.size() - 1)].duplicate()'''


replacement = '''func next_job(path: = 0) -> Dictionary:
\tvar paths: = GameData.job_paths(class_id)
\tvar _farmer_path: = path
\tif Save.has_meta("farmer_job_paths"):
\t\tvar _farmer_paths = Save.get_meta("farmer_job_paths", {})
\t\tif _farmer_paths is Dictionary and _farmer_paths.has(class_id):
\t\t\t_farmer_path = int(_farmer_paths[class_id])
\tvar job: Dictionary = paths[clampi(_farmer_path, 0, paths.size() - 1)].duplicate()'''
if 'Save.has_meta("farmer_job_paths")' not in text:
    text = replace_once(text, anchor, replacement)

open(out, "w", encoding="utf-8").write(text)
print("Player job and fall patch injected")
