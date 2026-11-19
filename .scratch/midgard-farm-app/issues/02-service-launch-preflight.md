# 02: Game launch and preflight in the service (Linux)

**What to build:** The service, not `run.sh`, launches the game with a preset on Linux. It runs every preflight check `run.sh` has today (game, profile, free space, preset, farmer patch mounted) and publishes the Known-good backup after a clean finish, under the same network isolation. A failed preflight maps to the same non-retryable outcome as exit 78.

**Blocked by:** 01.

**Status:** resolved

- [x] Every scenario of the current run-script test suite is ported to the service seam and passes.
- [x] Launching uses `unshare -cn` through the platform seam and refuses to start the game if isolation fails.
- [x] Arguments to the game are passed as a list; no shell string is built.
- [x] The Known-good backup is published only after a clean supervised finish and verified restorable, as today.
- [x] `run.sh` is left untouched; the old path still works.

## Comments

- 2026-11-19: Done in `b09d66a`; CI run 44586545407 green. On Linux: app 63 passed and 16 skipped, farmer 48 passed and 11 skipped; the runner cannot create user/network namespaces, so the real-`unshare` tests ran only locally, where 78 passed and 1 skipped. The launch tests are Linux-only; Windows AFK is ticket 10.
  - 15 of the 16 `run.sh` scenarios are ported in `tests/test_service_launch.py`. The `install.sh` one is covered by ticket 03.
  - Preflight runs in `run.sh` order: prerequisites (78), then the lock (1), then the running-game check (1). Exit 78 is reserved for preflight and isolation failures.
  - Shutdown signals request a finish with 45 s grace.
  - Known-good is stored as generations behind an atomic `backups/known-good/current` pointer, the same on both OSes.
  - Independent review: APPROVED after two rounds. Hand-off notes for the supervised session are in ticket 04.
