# Prep for ticket 06: how the app handles a Game update

Draft by a scout, 2026-11-19. These are not decisions. Every `file:line` was read in the main checkout. Items marked [INFERENCE] come from reading code, not from an observed Game update. Terms follow `GLOSSARY.md`.

## Facts

### 1. How a Game update is detected today

Detection lives in `farmer/run.sh` preflight. It runs on every launch, so on every supervisor attempt. A failed check calls `die`, which exits **78** (`run.sh:24-26`).

| Line | Check | Message |
|---|---|---|
| `run.sh:31` | `patches/state.json` exists | `no state.json ... (launch the game once)` |
| `run.sh:32` | `patch_farmer.info` exists | `patch_farmer.info missing; run ./build.sh && ./install.sh` |
| `run.sh:59` | the official patch named in the info exists | `official patch missing` |
| `run.sh:60` | `patches/patch_farmer.pck` exists | `farmer pack not installed; run ./install.sh` |
| `run.sh:61-62` | sha256 of the official patch equals `PATCH_SHA256` | `official patch changed (game updated); rebuild` |
| `run.sh:63-64` | sha256 of the installed farmer pck equals `PATCH_FARMER_SHA256` | `installed farmer pack is stale; run ./build.sh && ./install.sh` |
| `run.sh:65-66` | `state.json` has `.file == "patch_farmer.pck"` | `state.json does not mount patch_farmer.pck; run ./install.sh` |

- Other causes also exit 78: missing game binary, unwritable profile, under 200 MB free, bad or missing preset. At the exit-code level they look the same as a Game update.
- The supervisor copies the last `run: ...` line into `quarantine.json` as `detail` (`supervisor.py:196-199`).
- Only the "official patch changed" message is covered by a test (`tests/test_run_sh.py:177`).

### 2. What the game's updater does to `state.json` and the old patch (`analysis/src/updater.gd`)

- **Source.** The manifest comes from `updates.midgardsurvivors.com`, with a GitHub fallback (`:49-50`) and an 8 s timeout (`:54`). It is asked on every game start (`_ready`, `:183`).
- **Disabled when:** any user arg starts with `--` other than `--update-url` or `--lang` (`_enabled`, `:196-212`).
- **Blocking window.** The tree is paused (`_open_window`, `:480-488`) and the Operator must click accept. The game then downloads, checks sha256, decrypts and writes the new `patch_X.pck` (`_on_patch`, ~`:375-421`).
- **State is rewritten wholesale** (`:400-407`): `{"base","version","file":"<new official>"}`, plus the old `bridge` if there was one. Everything else is dropped, including the farmer's `"farmer":1` and `"file":"patch_farmer.pck"`. The game then restarts itself (`:420`).
- **The file it deletes as "old" is the previous `state.file`** (~`:390,410`). With the farmer installed that is `patch_farmer.pck`, so the **farmer pack is deleted**. The previous official file (`patch_0.2.3.pck`) is not referenced and stays on disk as an orphan. [INFERENCE: read from the code, not observed.]
- **A new game build clears everything.** If the game's base version no longer equals `state.base`, `_clear_patches()` deletes every file in `user://patches/` (`:96-99`, `:469-476`). This is an itch.io build change, not a patch. The app would then find no `state.json`, and `run.sh:31` says "launch the game once".
- **A bridge update** deletes both the old patch and the old bridge (`:296-303`, `:391-398`). In that case `run.sh:59` fires instead of line 60.
- **The offline farm cannot update the game.** Supervised launches run under `unshare -cn` (`run.sh:68-72,157-163`), so the updater's manifest request fails silently. A Game update happens only when the Operator plays the game normally.

### 3. Findings that change the question

- **A) After a real Game update, today's message is probably "farmer pack not installed" (`run.sh:60`), not "official patch changed".** The updater deleted `patch_farmer.pck`, and the old official file keeps its old hash. [INFERENCE] A GUI should classify the cause from state, not by matching message strings.
- **B) A Game update is visible from `state.json` alone.** `file` is no longer `patch_farmer.pck`, and `file` and `version` differ from `patch_farmer.info` `PATCH_FILE` and `PATCH_VERSION`. No hashing is needed. `build.sh:49-61` and `install.sh:42-45` already read the same fields.
- **C) `official-state.json` is written once and never refreshed** (`install.sh:62-65`, only `if [[ ! -f ... ]]`).
  - The live file records `base 0.1.259`, `bridge bridge_old_to_0.2.0.pck`, `file patch_0.2.3.pck`, `version 0.2.3`.
  - After a Game update it would point at a patch the game replaced.
  - Nothing reads it: `uninstall.sh` rebuilds state from `patch_farmer.info`.

### 4. `install.sh`

- **Refusals:**
  - the game is running (`:26`);
  - the official patch hash differs from the info (`:38-39`);
  - **`state.json` already mounts a different official patch**, so an old pack never overwrites newer official state (`:42-45`).
- **Backups.** Each install copies `state.json`, `profile*.json` and `profile.run*` into `backups/<stamp>/` (`:51-60`).
- **Writes.** The pack goes to `.tmp` and is then moved with `mv -f` (`:68-69`). State is edited the same way (`:70-81`): `file=patch_farmer.pck`, `farmer=1`, version stays official.
- **Last check.** The installed pack's hash is verified at the end (`:83-84`). If that fails, the new state stays in place; there is no rollback inside the script.
- **Other state keys.** `base` and `bridge` are preserved, because the loaded dict is re-dumped.

### 5. `uninstall.sh`

- It refuses while the game runs (`:16`).
- If state already points elsewhere, it only removes `patch_farmer.pck` and `farmer_build.json` (`:21-24`).
- Otherwise it takes `file` and `version` from **`patch_farmer.info`**, drops `farmer`, and deletes the pack (`:26-50`).
- It dies if the info is missing or the named official file is gone (`:35`).
- It keeps the profile, `farmer.cfg`, logs and backups.
- **It does not use `official-state.json`.**

### 6. `build.sh`: duration drivers and failure modes

**Duration is not measured anywhere in the repo.** `farmer_build.json` holds only `built_at`. Drivers, from reading the script:

- **Cache key** (`build.sh:101-102,131-133`): sha of the official patch, the bridge, the base pck `size-mtime`, the bytecode and the GDRE `size-mtime`.
- **A Game update is always a cache miss**, because the patch sha changes. A miss does three things:
  - extracts `save.gdc` and `player.gdc` from patch, then bridge, then base (`:117-126`);
  - runs two `--decompile` calls (`:139-145`);
  - keeps only the last 3 cache keys.
- **Every build** compiles 3 scripts, runs `--pck-patch` (which rewrites the whole official pck), and runs 3 `--list-files` checks (`:158-181`). It needs about 500 MB RAM (`:10`).
- **First build on a machine** downloads GDRE v2.7.4 with `curl` (`:78-85`).
- **Failure modes** (all exit non-zero):
  - state or game missing (`:39-42`);
  - official patch file missing (`:69`);
  - GDRE missing or download failed (`:86`);
  - script not found in patch, bridge or base (`:125`);
  - decompile fails (`:141,145`);
  - compile fails (`:164-166`);
  - **anchors broke:**
    - `tools/inject_hook.py` needs `var _timer: = 0.0` and `func _process(delta: float) -> void :` in the decompiled `save.gd` (`inject_hook.py:19-30`).
    - `tools/patch_player.py` needs the 3-line `next_job` block in `player.gd` (`patch_player.py:21-31`).
    - Both exit with a message like `Save hook: '_process' anchor not found`. This is the "a human must fix the injector" case.
  - `--pck-patch` produced nothing, or a required `.gdc` is missing (`:174-181`).
- **Build order leaves no pack behind.** `build.sh` removes the old `patch_farmer.pck` at `:168` and writes `patch_farmer.info` only at the end (`:184-196`). A build that fails in between leaves no pck and the old info. The previous pack is not kept.
- **`check_api.py` is not run by `build.sh`.**
  - It runs only through `tools/check.sh`, which `verify.sh` calls.
  - It reads `analysis/src`, which is the **0.2.3** decompile, so after a Game update it checks `farmer.gd` against old game source.
  - It is skipped when `analysis/src` is missing.
  - It is a best-effort identifier check, not proof (`check_api.py:5-8`).
  - Today the only automatic signal that the game's API changed is a runtime failure or the smoke.
- **Hard-coded values:** `FARMER_API=3` and bytecode `ebc36a7`. A Godot bytecode change breaks compile and needs a GDRE update.

### 7. Supervisor: exit 78, FATAL, quarantine

- **Classification** (`_classify`, `supervisor.py:268-281`):
  - exit 0 with `phase=done` means finished;
  - **exit 78 gives `("fatal","preflight_failed")`** (`:273-274`);
  - farmer terminal reasons in `FATAL_REASONS = {"cfg_invalid","checkpoint_corrupt"}` (`:51`) are fatal;
  - everything else is a failure with backoff.
- **Backoff and quarantine threshold.** Backoff is 15 s doubling to 600 s. Quarantine comes at 4 failures in 3600 s (`:64-70,150-159`). A fatal outcome skips the count and quarantines immediately (`:146-147`).
- **`_quarantine`** (`:172-189`):
  - writes `logs/supervisor-<stamp>/quarantine.json` with `reason`, `last_failure`, `detail` and the attempts;
  - notifies `quarantine`;
  - the supervisor exits **2**, and the systemd unit's `RestartPreventExitStatus=2` stops any restart.
- **Session after quarantine.** `farmer_supervisor_session` is deleted on any terminal outcome, quarantine included (`:425`), so the next start is a new session. The farmer's checkpoint is keyed by session id.
- **There is no path from quarantine back to running.** A Game update noticed at 02:00 costs the rest of the night today.
- **Policy lives in Python** (`Policy` dataclass, `:57-70`), so the app can call it or replace it.
- **Crash-loop quarantines:** these also exist, and a rebuild would not help them. Any automatic recovery must be limited to the stale-build cause.

### 8. How long `verify.sh --one-run` takes

Measured from `farmer/logs/verify-20261119-175605-300515/one-run.farmer.log`:

- **Farmer time:** `BOOT` 17:56:17 to `FINISH` 17:58:03, so **106 s** (`wall_s=104.96`, `game_s=480`).
- **Preset:** `one-run.json` has `max_runs 1`, `run_minutes 12`, `game_speed 3`, `speed 4`.
- **Assertions** (`verify.sh`, `assert_status`):
  - `phase=done` and not failed;
  - `wins>=1`, `last.victory`, `kills>0`, `zeny_gain>0`;
  - log marker `FINISH`;
  - no `SCRIPT ERROR|Parse Error|Invalid call|Cannot call method` in the game log.
- **Scenario timeout:** 300 s (`verify.sh:734`).
- **Fixed setup before the scenario**, not timed in any log:
  - waits on `.sandbox/verify.lock` for up to 1 h;
  - **dies if the game is running**;
  - copies the profile and hard-links the big pcks;
  - runs `tools/check.sh`, which includes the whole pytest suite and `check_api`;
  - installs into the sandbox.
- **Estimate: about 2–3 minutes end to end** [INFERENCE: 106 s measured, setup not measured].
- **Real profile untouched.** The install goes into the sandbox, so a smoke can run **before** the real install and leaves no trace.
- **What it does not cover.** It is not a Game update test. It does not run the supervisor or keep/maintenance (the preset has them off). The full `--all` is far longer; its per-scenario timeouts alone exceed 30 minutes.
- **Failures unrelated to the update are possible.** The soak in `verify-20261119-200202-570022` failed on `soak_check` while the other scenarios passed.

### 9. Other things the design depends on

- **One game per machine.** `run.sh:51`, `install.sh`, `uninstall.sh` and `verify.sh` all refuse while the game runs. A smoke cannot run during a night farm.
- **Known-good backup** (glossary: a restorable **profile** snapshot).
  - It is published only after a clean supervised finish (`run.sh:105-135,197-203`) into `backups/known-good`.
  - It holds profile files, not patch files, so it does not protect the farmer patch.
- **Notifications** are `notify-send` plus optional ntfy (`supervisor.py:306-330`). Events seen today: `fail`, `quarantine`, `stop`, `goal`.
- **Windows constraints from tickets 01 and 02:**
  - Windows takes the same official patch.
  - The farmer pck is built once on Linux and copied unchanged [INFERENCE until ticket 03].
  - So on Windows "rebuild" may mean "fetch the pck built for official patch sha X", not "run GDRE".
  - A hard exit gives code 0 on Windows, so the verdict comes from the terminal status.

## Rounds (draft)

The five open bullets of ticket 06 map to the rounds as follows.

| Round | Open bullet |
|---|---|
| A | When to notice a Game update |
| B | What the smoke is |
| C | The running AFK and quarantine |
| D | What the Operator sees and is sent |
| E | Backup, `official-state.json`, rollback |

### Round A: when the app notices a Game update

❓ **Q1. Where is a Game update detected?**
- (a) Only in `run.sh` preflight, as today. This needs no new code, but the night is lost first and the message is misleading (3A).
- (b) At app start and before every supervised launch, comparing `state.json` with `patch_farmer.info` (3B). It is a few file reads and needs no hashing. Preflight stays underneath as the safety net.
- (c) Also a live watcher on `state.json`. This adds a per-OS watcher for a case (b) already catches on the next click.

➡️ **(b).** Check at app start, before Start AFK, and when the window regains focus. Preflight exit 78 stays authoritative. No watcher.

❓ **Q2. What counts as "a Game update happened"?**
- (a) Any difference between state and info.
- (b) Four cases from state alone:
  - *current*: state mounts the farmer pack and the hashes match;
  - *Game update*: state mounts a different official file and the farmer pack is gone;
  - *pack removed or stale*: the official file is the same as in the info, as after `uninstall.sh` or a deleted pack;
  - *new game build*: `state.json` is missing or empty because the updater cleared `patches/` (Fact 2).
- (c) As (b), but a missing `state.json` is an error.

➡️ **(b).** The new-game-build case shows "start the game once and accept the update" and nothing automatic. Only *Game update* triggers the automatic rebuild. *Pack removed or stale* reinstalls without a rebuild.

❓ **Q3. Does the app act while the game process is alive?**
- (a) Rebuild anyway.
- (b) Wait until the game process is gone, then act.
- (c) Ask the Operator to close the game.

➡️ **(b).** Show "waiting for the game to close". `install.sh`, `uninstall.sh` and `verify.sh` already refuse while the game runs. The updater restarts the game itself after download (Fact 2), so wait a few seconds after it exits before acting. No prompt.

### Round B: what the smoke check is

❓ **Q4. What is the smoke?**
- (a) `verify.sh --one-run` in the sandbox. It boots the pack, one run settles with a win, kills > 0 and no script error. About 2–3 minutes. The real profile is untouched.
- (b) Install, boot headless about 20 s, look for `FARMER_LOADED api=3`, quit. It takes 30 s but only proves the pack mounts. A renamed game API would still pass.
- (c) The full `verify.sh --all`. Over 30 minutes, which delays the night.

➡️ **(a),** run in the sandbox **before** the real install (Q6). It is the smallest check that exercises a whole run and settlement, which is what a changed game API would break. Hard limit is the scenario's 300 s timeout.

❓ **Q5. How strict is the smoke?**
- (a) One attempt; any failed assertion is a failure.
- (b) One retry on failure.
- (c) One-run plus the supervised scenarios (5–8 more minutes).

➡️ **(b).** `wins>=1` can fail on a lost run unrelated to the update. A second failure counts as a failure. Do not add the supervised scenarios: they test the supervisor, which a Game update does not change.

### Round C: the running AFK and quarantine

❓ **Q6. What is the order of the automatic steps?**
- (a) Build, install into the real profile, smoke on the real profile, start. A failed smoke leaves a bad pack in the real profile, and `install.sh` has no rollback.
- (b) **Build, smoke in the sandbox, install into the real profile, start.** On failure nothing in the real profile changed.
- (c) As (b), plus one more real-profile launch.

➡️ **(b).** `verify.sh` already installs into its own profile copy. The real `state.json` stays as the game wrote it, an official working state, until the smoke passes.

❓ **Q7. What happens to a supervised session when a Game update is found?**
A Game update cannot land during a running farm. The farm's game is offline and there is one game per machine (Facts 2 and 9). The real case is a stale state found when an attempt is about to start or restart.
- (a) Nothing special: the attempt hits preflight and quarantines as today.
- (b) Run Q1's check before every attempt. If stale, rebuild, smoke, install, then run the attempt, with no failure counted.
- (c) Stop AFK and require a click.

➡️ **(b).** This is a pre-launch step in the supervisor path, not a failure.

❓ **Q8. Should a supervisor quarantined on "official patch changed" recover by itself after a successful rebuild?**
- (a) No. Quarantine stays final and the Operator presses Start. This keeps ADR 0003 intact but loses the night.
- (b) Yes, only for the stale-build cause.
  - Preflight 78 with state *Game update* (Q2) becomes a recoverable pre-launch condition.
  - Other 78s (missing game, bad preset, unwritable profile) and every crash-loop quarantine stay final.
  - A failed rebuild or smoke quarantines with a new reason (`build_failed` or `smoke_failed`).
- (c) Yes, for any quarantine after any successful rebuild.

➡️ **(b).** This turns the main cause of lost nights into a recovery without touching crash-loop semantics. It is attempted once per Game update, keyed by the official patch sha. A second failure for the same sha quarantines. ADR 0003 gets a new ADR for this one cause.

❓ **Q9. Which session continues across the rebuild?**
- (a) A new session.
- (b) The same session. Preflight exits before the game starts, so `farmer_session.json` is untouched and there is no unsettled run. History shows "interrupted by Game update, N min".
- (c) The Operator chooses.

➡️ **(b).**

### Round D: what the Operator sees and is sent

❓ **Q10. Which outcomes exist?**
- (a) Two: success and failure.
- (b) Four:
  - *Game update handled*;
  - *rebuild failed* (environment, GDRE or download);
  - *anchors broke* (the injector's anchor is gone, so the code must be fixed);
  - *smoke failed* (the pack mounts but a run does not settle, so `farmer.gd` is out of step with the game).
- (c) One per `die` message.

➡️ **(b).** Mapping:
- an `inject_hook.py` or `patch_player.py` anchor error is *anchors broke*;
- any other non-zero from `build.sh` is *rebuild failed*;
- a smoke assertion failure is *smoke failed*.

❓ **Q11. What is shown and sent?**
- (a) A status line in the window; notify only on failure.
- (b) **Success:** a history line ("Game update 0.2.3 → 0.2.4 handled, smoke OK, 3 min"). No notification if the Operator was there; one low-priority notification if it happened during an unattended night. **Failure:** a high-priority notification on desktop and ntfy with the outcome name, game version, one-line reason and log path. For *anchors broke*, add "the farmer needs a code fix; the game itself is unaffected and the official patch is mounted".
- (c) Always notify.

➡️ **(b).** The one-line reason is the last `run:` or `build:` line, as `quarantine.json` already does.

❓ **Q12. What does the app do after *rebuild failed* or *anchors broke*?**
- (a) Leave the old farmer pack in place.
- (b) Leave the game on the official patch as the game wrote it. Install nothing, mark the machine "farmer unavailable", and refuse Start AFK with the reason.
- (c) Retry on a schedule.

➡️ **(b).** After a Game update the old pack is already gone (Fact 2) and its hash cannot match the new patch. No scheduled retry, since build errors are deterministic. A "Check again" button covers the manual case.

### Round E: backup, `official-state.json`, rollback

❓ **Q13. What is the "known-good" for the farmer patch?**
- (a) Nothing. The official patch is the only fallback.
- (b) The last pack that passed the smoke, kept as pck plus info. It only helps while the game has not changed.
- (c) Keep N previous builds.

➡️ **(a)** for the update flow. After a Game update the previous pack is unusable by definition. Do not reuse the glossary's **Known-good backup**, which is a profile snapshot. A pack rollback for an **App update** belongs to ticket 07, where (b) would help.

❓ **Q14. What happens to `official-state.json`?**
- (a) Keep it as today: written once, never refreshed.
- (b) Refresh it on every detected Game update, from the official state the game just wrote, before installing.
- (c) Delete it and rebuild state from the info.

➡️ **(b).** It is the only copy of the game's own `base`, `bridge` and `version`, and today it is a stale record of 0.2.3 (3C). Keep the per-install `backups/<stamp>/state.json` as is.

❓ **Q15. How does rollback to the official patch work?**
- (a) As `uninstall.sh` today, from the info.
- (b) Restore `state.json` from `official-state.json` and delete the farmer pack. This works even when the info is stale or missing.
- (c) Both, with the info as fallback.

➡️ **(b),** with a check that the official file named in the restored state exists. If it does not, show "start the game and accept the update". Refuse while the game runs. After a failed rebuild, state is already official, so rollback is just removing leftovers.

❓ **Q16. Who removes the orphaned old official patch?**
- (a) The app deletes `patch_*.pck` that `state.json` does not name.
- (b) Leave it. It is the game's file, and deleting could remove something a bridge needs.
- (c) Delete only after a smoke pass, and only if neither `file` nor `bridge.file` names it.

➡️ **(b).** Revisit if disk becomes a problem; `run.sh` already has a 200 MB free-space preflight.

## Not in this ticket

- **Stack:** which stack runs these steps, and whether `build.sh` and `install.sh` become app code, is ticket 04.
- **Windows:** build on Windows or copy the Linux pck is tickets 02 and 03. The flow above works for both if "rebuild" can be "fetch the pck for sha X".
- **App update:** ticket 07, including an **App update** that changes `farmer.gd` and needs a rebuild without a Game update.

## Facts I could not establish

- **Build duration.** No timing is recorded anywhere.
- **What the Operator actually sees after a real Game update.** No log of one exists, so 3A is inferred from `updater.gd` and `run.sh`.
- **Whether the game restarts itself reliably after the update.** It calls `OS.set_restart_on_exit` (`updater.gd:420`); this matters for Q3.
