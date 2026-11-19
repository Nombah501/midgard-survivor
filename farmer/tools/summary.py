#!/usr/bin/env python3
"""What the current (or last) farmer session earned: ./tools/summary.py"""
import collections
import json
import os
from pathlib import Path

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "godot/app_userdata/Midgard Survivors"

status = json.loads((DATA / "farmer_status.json").read_text(encoding="utf-8"))
session = status["session"]
journal = DATA / "farmer_runs.jsonl"
rows = [row for line in (journal.read_text(encoding="utf-8").splitlines() if journal.exists() else [])
        if line.strip() for row in [json.loads(line)] if row.get("session") == session]
totals = status["totals"]
hours = sum(r.get("wall_s", 0) for r in rows) / 3600
materials = collections.Counter()
for r in rows:
    materials.update(r.get("materials") or {})

print(f"сессия {session}: {status['phase']} ({status.get('finish_reason') or 'идёт'})")
print(f"забегов {totals['runs']} (побед {totals['wins']}, потеряно {totals['lost']}), {hours:.1f} ч в забегах")
per_hour = f" ({totals['zeny'] / hours:,.0f}/ч)" if hours else ""
print(f"zeny +{totals['zeny']:,}{per_hour}  xp +{totals['xp']:,}  kills {totals['kills']:,}")
print(f"карт +{sum(r.get('cards_gain', 0) for r in rows)}  coins +{totals['coins']}  ymir +{totals['ymir']}")
print("материалы:", ", ".join(f"{k} {v}" for k, v in materials.most_common()) or "—")
