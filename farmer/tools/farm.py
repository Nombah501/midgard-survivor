#!/usr/bin/env python3
"""Choose a character and a farming location, then launch run.sh.

Examples:
  ./tools/farm.py --list
  ./tools/farm.py --char sinx --stage prontera --danger 25
  ./tools/farm.py --char sniper --stage payon --danger 20
  ./tools/farm.py --class archer --job-path 0 --stage orc --danger 15

The config is generated from presets/synx-hell.json; the preset is not edited.
The farmer still uses the selected class's profile pick_order/pick_limits.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS_PATH = ROOT / "targets.json"
BASE_PRESET = ROOT / "presets" / "synx-hell.json"


def load_targets():
    with TARGETS_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def show_list(targets):
    print("Characters:")
    for name, c in sorted(targets["characters"].items()):
        print(f"  {name:<12} {c['class']}/{c['job_path']:<2} {c['label']}")
    print("Stages:")
    for name, label in sorted(targets["stages"].items()):
        print(f"  {name:<14} {label}")


def main():
    targets = load_targets()
    parser = argparse.ArgumentParser(
        description="Pick a character/location and run the farmer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--list", action="store_true", help="list characters and stages")
    parser.add_argument("--char", help="named character from targets.json")
    parser.add_argument("--class", dest="class_", help="base class id, e.g. thief")
    parser.add_argument("--job-path", type=int, help="job path index (default 0)")
    parser.add_argument("--stage", default="prontera", help="stage id from --list")
    parser.add_argument("--danger", type=int, default=25, help="fixed danger (default 25)")
    parser.add_argument("--speed", type=float, help="override Engine.time_scale")
    parser.add_argument("--run-minutes", type=float, help="override run timeout in game minutes")
    parser.add_argument("--max-runs", type=int, help="override session run cap")
    parser.add_argument("--preset", default=str(BASE_PRESET), help="base preset JSON")
    parser.add_argument("--dry-run", action="store_true", help="write and print config, do not run")
    args = parser.parse_args()

    if args.list:
        show_list(targets)
        return 0

    if args.char and args.class_:
        parser.error("use --char or --class, not both")
    if args.char:
        c = targets["characters"].get(args.char)
        if c is None:
            parser.error(f"unknown character {args.char!r}; use --list")
        cid = c["class"]
        job_path = int(c["job_path"])
    else:
        cid = args.class_ or "thief"
        job_path = 0 if args.job_path is None else args.job_path
    if args.job_path is not None and args.char:
        parser.error("--job-path is for --class; named characters already have it")

    if args.stage not in targets["stages"]:
        parser.error(f"unknown stage {args.stage!r}; use --list")
    if not 1 <= args.danger <= 30:
        parser.error("--danger must be 1..30")
    if job_path < 0:
        parser.error("--job-path must be >= 0")

    base = Path(args.preset)
    if not base.is_file():
        parser.error(f"preset not found: {base}")
    with base.open(encoding="utf-8") as fh:
        cfg = json.load(fh)

    cfg["class"] = cid
    cfg["job_paths"] = {cid: job_path}
    cfg["stage"] = args.stage
    cfg["danger"] = args.danger
    cfg["auto_danger"] = False
    if args.speed is not None:
        cfg["speed"] = args.speed
    if args.run_minutes is not None:
        cfg["run_minutes"] = args.run_minutes
    if args.max_runs is not None:
        cfg["max_runs"] = args.max_runs

    out = ROOT / ".build" / "farm.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)

    label = targets["characters"].get(args.char, {}).get("label", cid)
    print(f"farm: {label} class={cid}/{job_path} stage={args.stage} danger={args.danger}")
    print(f"farm: config {out}")
    if args.dry_run:
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
        return 0

    return subprocess.run([str(ROOT / "run.sh"), str(out)], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
