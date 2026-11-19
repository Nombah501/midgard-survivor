# 11: Packaging and release CI

**What to build:** A `v*` tag makes GitHub Actions run the tests on Linux and Windows, build a PyInstaller onedir per OS containing the window and the service, and publish a private release with sha256 files.

**Blocked by:** 08.

**Status:** resolved

- [x] Each onedir starts both entry points on a clean runner without a system Python.
- [x] The release carries one archive per OS and its sha256.
- [x] A non-tag push runs tests only.

## Comments

- 2026-11-20: the app reads several build inputs from the repo's `farmer/` tree, and each must ship with the onedir:
  - `core.farmer_patch.build`: the `.gd` sources and the injectors.
  - `core.smoke`: the one-run preset.
  - The window (ticket 08): character picker from `farmer/targets.json`, presets from `farmer/presets/`.
  - Bundle them as package data and resolve them through one function, not `parents[N]` paths.
  - CI needs PySide6 offscreen rendering on both runners (the window test).
- 2026-11-20: Done in `c9beff1`, `6b24874`, `6884271`, `57c4cd6`; released as v0.1.0 by run 44638183324. All five jobs passed: test ×2, package ×2, release.
  - `midgard_farm.assets` is the one resolver for the farmer inputs, presets, catalog and version. The Farmer hash is the same in the checkout and in the frozen build (`2d4c266a…` on both runners).
  - Onedir `midgard-farm/` holds `midgard-farm-service` (windowless on Windows, no Qt) and `midgard-farm` (the window). The Qt payload is pruned: the onedir is 207 MiB on Linux and 118 MiB on Windows, and the archives are 80.9 MiB and 45.7 MiB.
  - CI smoke-tests the extracted archive with no Python on PATH. A non-tag push ran tests only (run 44622349524).
  - The release job is re-runnable (`gh release upload --clobber`). PEP 440 prerelease versions publish as GitHub prereleases. The tag must equal the package version.
  - Independent review: CHANGES_REQUIRED (idempotency, payload size); fixed.
  - Release fixes found by the first tag runs: path aliases in `check_onedir`, the Fusion/Basic `impl` modules on Windows, and Windows `game_pids` listing terminated processes (`1e3e8bd`).
