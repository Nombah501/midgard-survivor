# 11: Packaging and release CI

**What to build:** A `v*` tag makes GitHub Actions run the tests on Linux and Windows, build a PyInstaller onedir per OS containing the window and the service, and publish a private release with sha256 files.

**Blocked by:** 08.

**Status:** ready-for-agent

- [ ] Each onedir starts both entry points on a clean runner without a system Python.
- [ ] The release carries one archive per OS and its sha256.
- [ ] A non-tag push runs tests only.

## Comments

- 2026-11-20: the app reads several build inputs from the repo's `farmer/` tree, and each must ship with the onedir:
  - `core.farmer_patch.build`: the `.gd` sources and the injectors.
  - `core.smoke`: the one-run preset.
  - The window (ticket 08): character picker from `farmer/targets.json`, presets from `farmer/presets/`.
  - Bundle them as package data and resolve them through one function, not `parents[N]` paths.
  - CI needs PySide6 offscreen rendering on both runners (the window test).
