# 14: Remaining verify scenarios and soak in Python

**What to build:** Every other scenario of `verify.sh` (supervised runs, operator commands, fault injection) and the soak check are ported to Python on top of the smoke run. The soak stays Linux-only.

**Blocked by:** 04, 06.

**Status:** resolved

- [x] Each `verify.sh` scenario has a Python equivalent with the same assertions.
- [x] The soak check runs on Linux and produces the same verdicts as today.
- [x] Live-game scenarios stay out of CI.

## Comments

- 2026-11-20: Done in `4637737` and `fb0aee4` (review fixes). CI run 44616283688 passed on Linux and Windows.
  - The CLI is `python -m midgard_farm.verify --scenario … | --all | --soak=HOURS`. It covers all 15 `verify.sh` scenarios on `core.smoke`'s sandbox, with `verify-*` supervisor sessions.
  - Soak verdict parity is proven against `farmer/tools/soak_check.py` on 13 shared fixtures.
  - Linux-only pieces (external kill, soak) are behind the platform seam. On Windows, `--all` reports them as SKIP.
  - Independent review: APPROVED. No assertion was dropped or weakened. Its minors are fixed.
  - Operator steps, on Linux: close the game, restore the official patch and let the app build its candidate (ticket 15 order), then run:
    - `.venv/bin/python -m midgard_farm.verify --scenario one-run --keep`
    - `.venv/bin/python -m midgard_farm.verify --all`
    - `.venv/bin/python -m midgard_farm.verify --soak=9 --keep`
