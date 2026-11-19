# 03: Windows test bench

Type: task
Status: resolved
Blocked by: none

## Question

Facts that only the real Windows machine can give. The operator does the steps (HITL); the agent writes down the answers.

1. Install Midgard Survivors on the Windows machine (itch: https://nearq.itch.io/midgard-survivors) and launch it once. If it offers the official patch, accept it.
2. Record: the game version from the main menu, and the path to the game folder.
3. Open `%APPDATA%\Godot\app_userdata\` and check whether a `Midgard Survivors` folder exists. If not, find where `profile.json` and `patches\state.json` are. Send the full path.
4. Send the contents of `patches\state.json` and the list of files in `patches\` with their sizes.
5. Python installed? (`py --version`) Admin rights on this account? Windows version (`winver`).
6. Is the machine on at night and not going to sleep? (power plan)

7. Confirm the farmer patch builds on Windows itself (06 Q17: every machine builds its own; nothing is copied between machines). The agent prepares the exact commands when you get here:
   - the version of the game/engine and the base/bridge state from `state.json`;
   - the SHA-256 of the official patch on Windows matches Linux (02's shared-payload claim);
   - GDRE v2.7.4 `--headless` on Windows builds `patch_farmer.pck` from the Windows official patch; mount it while keeping Windows' own `state.json` metadata. For comparison only, note whether its SHA-256 equals the Linux build;
   - one offline test run: `FARMER_LOADED api=3` in `farmer.log` and a completed run;
   - restore the official state and check the game launches unmodified.

Answer: the facts above. They unblock 02 (confirmation), 04 and 08.

## Prep

1. Install and launch the game once on Windows. Accept the official patch if offered, and note the version shown in the main menu; the executable's file version may differ.
2. Copy [03-windows-bench.ps1](../assets/03-windows-bench.ps1) to a writable folder on Windows. Open PowerShell in that folder as the same Windows account that launched the game; no elevation is needed.

   ```powershell
   powershell -ExecutionPolicy Bypass -File 03-windows-bench.ps1
   ```

   If the report has no single `Game.ExePath`, rerun with `-GameDir "C:\path\to\game"` after the script filename. The collector does not launch the game or change the game, profile, patches, or power settings. Its only file output is a new `03-windows-bench-*.json` next to the script.
3. Paste the printed JSON (or the saved JSON) back here with the main-menu version and whether the machine will stay on and awake overnight. If `SelectedUserData` is missing or points to a folder without both markers, include the actual `user://` path if you know it.

### Step 7: separate guided run

After these facts arrive, the agent will provide a second guided script for the operator to verify the hashes, build the farmer patch with GDRE on Windows and mount it, complete one offline run, and restore and verify the official state. The collector above does none of step 7.

## Answer

Items 1–6 (gpu-pc, operator run of `03-windows-bench.ps1`, report `03-windows-bench-20261119-212506-106.json`, 2026-11-19):

1. **Game:** installed from itch at `C:\Users\User\Downloads\midgard-survivors-midgard-survivors-windows\MidgardSurvivors.exe`; main menu shows **0.2.3**; the exe's file version is **0.1.272.0** (the base). No separate `MidgardSurvivors.console.exe`.
2. **`user://` is `%APPDATA%\Godot\app_userdata\Ragnarok Survivors`**, not `Midgard Survivors`. The Linux profile lives under `Midgard Survivors` with base **0.1.259**; the newer Windows base 0.1.272 carries a different project name. [INFERENCE] A Game reinstall on Linux to base ≥ 0.1.272 would move `user://` to a new folder, so the app must locate the profile by its markers (`profile.json` + `patches/state.json`), never by a hard-coded name. Today every farmer script hard-codes `Midgard Survivors`.
3. **`state.json`:** `{"base":"0.1.272","bridge":{"file":"bridge_old_to_0.2.0.pck","version":"0.2.0"},"file":"patch_0.2.3.pck","version":"0.2.3"}`.
4. **`patches\`:** `bridge_old_to_0.2.0.pck` (487 654 500 B) and `patch_0.2.3.pck` (11 720 768 B). **Both SHA-256 identical to Linux** (`c16dca87…3777`, `680b5dfd…1b66`), confirming 02's shared-payload claim. Only the base differs (0.1.272 vs 0.1.259).
5. **Windows 11 Pro 25H2** (build 26200.9711). The account is an **administrator** (the report ran elevated). **No Python** (`python` is the Store alias, `py` absent): the Windows app cannot assume a system Python (input for 04).
6. **Power:** Balanced plan; on AC, sleep after = never, hibernate after = never; wake timers on. The machine stays up overnight on AC.

Collector bug fixed: Windows PowerShell 5.1 serialized `Get-Content -Raw` with its provider properties, making the report ~80 MB; the state is now cast to `[string]`.

Item 7: kit `assets/03-windows-step7.zip` (script `03-windows-step7.ps1`, kit sources, `expected.json`). Expected values come from a Linux rebuild of the same sources, which is byte-deterministic (two `--pck-patch` runs and the installed pack all hash `1e6678e9…ff6c`).

Item 7 (gpu-pc, `03-windows-step7.ps1`, report `03-windows-step7-20261119-220925.json`): **every check passed.**

- **Build on Windows works and is byte-identical to Linux.** GDRE v2.7.4 headless took `save.gdc` and `player.gdc` from the official patch (`from=patch`). The decompiled `save.gd` and `player.gd`, all three compiled `.gdc` files and `patch_farmer.pck` (`1e6678e9…ff6c`) match Linux byte for byte. The build took **16 s** (decompile, compile, pck-patch; GDRE download excluded, 7 s). This confirms 06 Q17: each machine builds its own pack.
- **The Windows base 0.1.272 runs the pack.** One offline run under `--headless` with `FARMER_SESSION=1` printed `FARMER_LOADED api=3`, went BOOT → START → BOSS_WON → SETTLE → FINISH, and wrote status `phase=done`, `max_runs`, 1 run, 1 win, 2564 kills, +77 601 zeny. There were no script errors. Game time was 116 s, the same as Linux (106 s).
- **Restore works.** `state.json` is byte-identical to before (`1025fce6…`), the farmer pack is removed, and the profile files are restored, so the run's gains were reverted. A vanilla headless launch stayed alive for 25 s with no `FARMER_LOADED` and no script errors.
- **Exit code unavailable.** Windows PowerShell gave `ExitCode = null` for the hard-exited game, which fits 01: the verdict comes from the terminal status, never the exit code.
- **Godot log.** The run left no readable `logs\godot.log` tail, and `FARMER_LOADED` was found in redirected stdout. [INFERENCE] The app must capture the game's stdout on Windows rather than rely on `godot.log`.
- **Pitfall for the Windows app.** Windows PowerShell's `Start-Process -ArgumentList` does not quote arguments, and `user://` contains a space (`Ragnarok Survivors`). The first attempt silently fell back to the base pck. Every process argument must be quoted explicitly.
- **Separate progress.** The Windows profile has its own progress (BOOT zeny 178 M vs about 90 M on Linux), consistent with independent profiles. Whether it came from the game's CloudSave is unknown.

Network: the run used the game's normal network (no isolation) and the updater did not interfere, because 0.2.3 is current. Input for 08.
