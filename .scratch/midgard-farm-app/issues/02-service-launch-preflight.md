# 02: Game launch and preflight in the service (Linux)

**What to build:** The service, not `run.sh`, launches the game with a preset on Linux. It runs every preflight check `run.sh` has today (game, profile, free space, preset, farmer patch mounted) and publishes the Known-good backup after a clean finish, under the same network isolation. A failed preflight maps to the same non-retryable outcome as exit 78.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] Every scenario of the current run-script test suite is ported to the service seam and passes.
- [ ] Launching uses `unshare -cn` through the platform seam and refuses to start the game if isolation fails.
- [ ] Arguments to the game are passed as a list; no shell string is built.
- [ ] The Known-good backup is published only after a clean supervised finish and verified restorable, as today.
- [ ] `run.sh` is left untouched; the old path still works.
