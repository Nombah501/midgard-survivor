# 06: Smoke run in Python

**What to build:** The app can prove a farmer patch with one sandboxed run: copy the profile into a sandbox, install the pack there, play the one-run preset and judge it. This is the smoke of the Game update pipeline and the Python form of `verify --one-run`.

**Blocked by:** 02, 03.

**Status:** resolved

- [x] The sandbox never touches the real profile; big packs are linked, not copied.
- [x] A 300 s hard limit applies, with one retry; the second failure is final.
- [x] Pass requires status done and not failed, at least one win with the last run a victory, kills > 0, zeny gain > 0, a FINISH marker and no script errors in the game output.
- [x] Game output is captured from the process directly (Windows does not provide `godot.log`).
- [x] It refuses while the game runs.

## Comments

- 2026-11-19: Done in `8b3e95b`. CI run 44591142864 passed on Linux and Windows after a rerun. The first Linux attempt aborted at interpreter shutdown in the legacy farmer suite: the daemon ntfy thread in `farmer/tools/supervisor.py` is flaky, which goes away with cutover.
  - API: `core.smoke.run_smoke(os_, profile) -> SmokeVerdict` (outcome PASSED/FAILED/BUSY, `reason`, `attempts`, `log_path`).
  - Packs are hard-linked, with a plain copy across volumes and no symlinks, because Windows symlinks need admin.
  - Godot `user://` is redirected through the platform seam: `XDG_DATA_HOME` on Linux, `APPDATA` on Windows.
  - The smoke cfg is pinned to `farmer/presets/one-run.json` plus overrides by a test.
  - Independent review: CHANGES_REQUIRED (symlink fallback); fixed.
  - Operator step, with the game closed and an app-built candidate: `.venv/bin/python -c 'from midgard_farm import platform; from midgard_farm.core.profile import find_profile; from midgard_farm.core.smoke import run_smoke; p = platform.current(); v = run_smoke(p, find_profile(p.godot_user_data_root())); print(v); raise SystemExit(0 if v.passed else 1)'`
