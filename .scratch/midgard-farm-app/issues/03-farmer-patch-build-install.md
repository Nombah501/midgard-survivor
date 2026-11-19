# 03: Farmer patch build, install and restore in Python

**What to build:** The app builds the farmer patch, installs it into the profile and can restore the official patch, without bash. The patch info records the Farmer hash. GDRE v2.7.4 is downloaded on first use and verified against a pinned sha256.

**Blocked by:** 01.

**Status:** ready-for-agent

- [ ] The build extracts save/player from the patch, then the bridge, then the base, then decompiles, injects, compiles and pck-patches; the three files are verified inside the result.
- [ ] The Farmer hash covers the farmer and save-hook sources, the injectors, the farmer API and the bytecode, and is written to the patch info.
- [ ] A missing injector anchor is reported as a distinct error class from any other build failure.
- [ ] Install backs up state and profile files, replaces the pack atomically, keeps base/bridge/version, verifies the installed hash and restores the backup on failure; it refuses while the game runs.
- [ ] Restore official patch rebuilds `state.json` from `official-state.json`, deletes the farmer pack, refuses while the game runs and reports a missing official file.
- [ ] Tested with a fake GDRE at the service seam; on the Linux machine a real build hashes to the same pack as `build.sh` for the same inputs.
