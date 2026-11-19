# 07: Game update states and pipeline

**What to build:** Before each attempt, at service start and on each command, the service classifies the machine as current, Game update, farmer patch removed or stale, or Game reinstall. On a Game update or a Farmer hash change it refreshes `official-state.json`, builds, smokes, installs and then runs the attempt, without counting a failure. On failure it quarantines with `build_failed`, `anchors_broken` or `smoke_failed`, leaves the official patch mounted and blocks retries per (official patch sha, Farmer hash) until Check again, a new Game update or a farmer-changing App update.

**Blocked by:** 04, 06.

**Status:** resolved

- [x] The four states are classified from `state.json`, the patch info and the Farmer hash, with no game-file hashing.
- [x] While the game runs the state is 'waiting for the game to close'; work starts after a short grace period once the game is gone.
- [x] Pipeline order is: refresh official state, build, smoke in the sandbox, install, attempt; the real profile is untouched on any failure.
- [x] A pre-launch rebuild never increments the failure count; the three new reasons quarantine at once; other preflight failures and crash-loop quarantines behave as before.
- [x] The retry block and its three lifting conditions are covered by service-seam tests with fake game and fake GDRE.
- [x] A Game reinstall triggers nothing automatic and reports 'start the game and accept the update'.
- [x] History lines and notifications are emitted for every outcome as specified.
- [x] ADR 0005 holds as written.

## Comments

- 2026-11-19 (review of ticket 03): `farmer_patch.snapshot_official_state` raises while the farmer pack is mounted. Pipeline step 1, refreshing the official state, works after a Game update because the farmer pack is gone by then. On a Farmer hash change the farmer pack is still mounted, so the pipeline must skip the refresh and keep the existing `patches/official-state.json`. Cover this with a test.
- Install re-checks for a running game after staging, but a narrow window remains before the state write, and no test covers it. The pipeline's "game running → wait" gate is the primary guard.
- 2026-11-19 (from ticket 06): smoke is `core.smoke.run_smoke(os_, profile)`. BUSY means the game is open: wait, do not quarantine. FAILED, after its own single retry, maps to `smoke_failed`; do not retry it again in the pipeline.
- 2026-11-20: Done in `dc1db40` (pipeline module), `22e031e` (wiring into the service) and `fd6b4c3` (review fixes). CI run 44602878630 passed on Linux and Windows.
  - API: `game_update.classify(os_, profile)` and `GameUpdatePipeline(os_, profile, events).run(check_again=…)`, which returns Ready, Wait, Quarantine or Blocked. The command is `commands.submit(os_, "check_again")`.
  - The update check runs at service start, on idle commands, and before each attempt. A Check again sent during a live attempt is refused and recorded.
  - `game_update_handled` is sent only for unattended rebuilds before an attempt.
  - A stop request is honoured between stages; no install starts after a stop. A GDRE call already in flight is not interrupted.
  - Independent review: APPROVED, and its six minors are fixed.
  - Open: the narrow install race noted above.
