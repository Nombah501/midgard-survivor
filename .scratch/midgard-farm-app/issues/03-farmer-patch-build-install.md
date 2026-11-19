# 03: Farmer patch build, install and restore in Python

**What to build:** The app builds the farmer patch, installs it into the profile and can restore the official patch, without bash. The patch info records the Farmer hash. GDRE v2.7.4 is downloaded on first use and verified against a pinned sha256.

**Blocked by:** 01.

**Status:** resolved

- [x] The build extracts save/player from the patch, then the bridge, then the base, then decompiles, injects, compiles and pck-patches; the three files are verified inside the result.
- [x] The Farmer hash covers the farmer and save-hook sources, the injectors, the farmer API and the bytecode, and is written to the patch info.
- [x] A missing injector anchor is reported as a distinct error class from any other build failure.
- [x] Install backs up state and profile files, replaces the pack atomically, keeps base/bridge/version, verifies the installed hash and restores the backup on failure; it refuses while the game runs.
- [x] Restore official patch rebuilds `state.json` from `official-state.json`, deletes the farmer pack, refuses while the game runs and reports a missing official file.
- [x] Tested with a fake GDRE at the service seam; on the Linux machine a real build hashes to the same pack as `build.sh` for the same inputs.

## Comments

- 2026-11-19: Done in `0be0e81`; CI run 44585126374 green on Linux and Windows. API: `midgard_farm.core.farmer_patch` (`build`, `install`, `restore`, `farmer_hash`, `snapshot_official_state`; `AnchorsBroken` ⊂ `BuildFailed`, `InstallFailed`, `GameRunning`, `OfficialPatchMissing`). Build output and `PatchInfo` live in the app data dir (`farmer/`). The official state snapshot is per profile at `patches/official-state.json`. Install backups go to `backup_dir`, by default `farmer/backups` in the app data dir. Fake-GDRE tests drive the module API; the service is wired to it in ticket 07. A real build on the Linux machine (existing GDRE archive, temp output) gave `1e6678e9…ff6c`, equal to `build.sh`'s `PATCH_FARMER_SHA256`. Independent review: APPROVED. Its open minors are in the comments of tickets 07, 10 and 15.
