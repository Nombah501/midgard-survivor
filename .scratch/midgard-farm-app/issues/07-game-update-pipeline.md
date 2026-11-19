# 07: Game update states and pipeline

**What to build:** Before each attempt, at service start and on each command, the service classifies the machine as current, Game update, farmer patch removed or stale, or Game reinstall. On a Game update or a Farmer hash change it refreshes `official-state.json`, builds, smokes, installs and then runs the attempt, without counting a failure. On failure it quarantines with `build_failed`, `anchors_broken` or `smoke_failed`, leaves the official patch mounted and blocks retries per (official patch sha, Farmer hash) until Check again, a new Game update or a farmer-changing App update.

**Blocked by:** 04, 06.

**Status:** ready-for-agent

- [ ] The four states are classified from `state.json`, the patch info and the Farmer hash, with no game-file hashing.
- [ ] While the game runs the state is 'waiting for the game to close'; work starts after a short grace period once the game is gone.
- [ ] Pipeline order is: refresh official state, build, smoke in the sandbox, install, attempt; the real profile is untouched on any failure.
- [ ] A pre-launch rebuild never increments the failure count; the three new reasons quarantine at once; other preflight failures and crash-loop quarantines behave as before.
- [ ] The retry block and its three lifting conditions are covered by service-seam tests with fake game and fake GDRE.
- [ ] A Game reinstall triggers nothing automatic and reports 'start the game and accept the update'.
- [ ] History lines and notifications are emitted for every outcome as specified.
- [ ] ADR 0005 holds as written.
