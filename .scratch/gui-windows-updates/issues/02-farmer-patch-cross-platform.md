# 02: Is the farmer patch shared between Linux and Windows?

Type: research
Status: resolved
Blocked by: none

## Question

Can a farmer patch built on Linux be mounted unchanged by the Windows build of the game?

Charting found: the game's manifest has no Windows section, so Windows takes the same `patch_0.2.3.bin` as Linux. A pck holds bytecode `ebc36a7`.

Check:
- whether the official patch is identical across platforms (manifest sections, the `pc` feature in `updater.gd` `_enabled`);
- whether the farmer patch contains platform-specific resources (`build.sh`, the list of files in the pck);
- whether `state.json` / `load_resource_pack` treat paths differently on Windows.

The answer decides whether to build on every machine (GDRE on Windows) or once, then copy. Mark guesses [INFERENCE]. 03 confirms them on the real Windows machine.

## Answer

**Conditional yes [INFERENCE]:** build once on Linux for the matching official desktop patch and copy `patch_farmer.pck` unchanged; no Windows GDRE is needed if ticket 03 passes. Windows and Linux select the same official 0.2.3 payload. The inspected farmer PCK is format 4 (engine header 4.7.2), includes `ebc36a7` GDScript replacements and no native binaries, and is mounted through a `user://patches` filename, not an OS path. The Windows runtime must support that format and bytecode and have a compatible native base or bridge.

**Ticket 03:** confirm the actual Windows game/engine version, `user://` location and local base/bridge state; verify the decrypted official PCK and unchanged farmer PCK SHA-256s. Preserve Windows' own state metadata, then verify `FARMER_LOADED api=3`, one completed offline test run, and restoration of the official state.

Findings: branch `research/farmer-patch-cross-platform`, file `research/farmer-patch-cross-platform.md` in worktree `../midgard-research-farmer-patch-cross-platform`.
