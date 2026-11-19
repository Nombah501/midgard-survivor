# Midgard Farm on Linux and Windows — Spec

Status: ready-for-agent

Source: the wayfinder map [`../gui-windows-updates/map.md`](../gui-windows-updates/map.md) and its resolved tickets 01–07; ADRs 0005–0007. Implementation tickets: `issues/` in this directory. Tickets 08 and 09 were deferred by the operator; this spec uses their recorded defaults.

## Problem Statement

The farmer runs reliably only on the operator's Linux machine, and only from a terminal: bash scripts build and install the farmer patch, a Python supervisor runs the AFK session under systemd, and an old Qt/C++ window launches an outdated script. The operator also has a Windows machine where nothing of this works. bash and Python are missing there, and every script hard-codes the Linux profile folder.

Every Game update deletes the farmer patch. The next supervised attempt then fails preflight, the session goes into quarantine, and the rest of the night is lost until the operator runs `build.sh` and `install.sh` by hand. Changes to the farmer itself reach a machine only by hand.

## Solution

Midgard Farm becomes one application for Linux and Windows. The operator installs it once per machine, starts AFK from a window and reads the night's results there; the terminal is for development only.

AFK runs as a background service on each OS, and the window is a remote control: closing it does not stop the night. The two machines keep independent profiles and share nothing.

The app handles a Game update on its own. Before every launch it notices the change, rebuilds the farmer patch on that machine, proves it with a smoke run in a sandbox, installs it and starts. It asks the operator only when that fails, and then leaves the game on the official patch.

The app updates itself as well. A tagged release is built by CI and downloaded by the service, which installs it between sessions and reverts by itself if the new version does not come up.

## User Stories

### AFK control
1. As the operator, I want to start an AFK session from the window by choosing a character and a preset, so that I never open a terminal.
2. As the operator, I want the window to remember the last character and preset, so that a nightly start is one click.
3. As the operator, I want the phase and the last heartbeat at the top of the window, so that I can tell at a glance whether the farm is alive.
4. As the operator, I want income and the current run shown just below, so that I can see what the night is earning.
5. As the operator, I want Pause and Resume, so that I can stop new runs from starting without losing the current one.
6. As the operator, I want Finish, so that the current run settles and the session ends cleanly.
7. As the operator, I want Abort, with one confirmation that names what will be lost, so that I can stop at once without surprise.
8. As the operator, I want closing the window to leave the AFK session running, so that the window is only a remote control.
9. As the operator, I want reopening the window to show the live session state, so that I can check in at any time.
10. As the operator, I want Start refused with a plain reason when the machine cannot farm (game not found, farmer unavailable, quarantine), so that I know what to fix.
11. As the operator, I want the app to find the game and the profile by itself, so that I configure no paths.

### History and results
12. As the operator, I want one history line per AFK session with its outcome and totals, so that I can see past nights.
13. As the operator, I want Game update and App update events interleaved with the sessions in history, so that I can see what changed between nights.
14. As the operator, I want the last night expandable to its totals, rewards per hour and materials, so that I get the morning summary without a terminal.

### Game update
15. As the operator, I want the app to tell a Game update from a removed or stale farmer patch and from a Game reinstall, so that it reacts correctly to each.
16. As the operator, I want the app to rebuild, smoke and install the farmer patch by itself after a Game update, so that the next night farms without me.
17. As the operator, I want the rebuild to happen before a supervised attempt without counting as a failure, so that a Game update does not cost the night.
18. As the operator, I want the app to wait while the game is running and to start once it has closed, so that it never touches files under a live game.
19. As the operator, I want the smoke run to happen in a sandbox before anything touches my real profile, so that a bad farmer patch never lands there.
20. As the operator, I want one automatic retry of a failed smoke, so that one unlucky lost run does not block the farm.
21. As the operator, I want a failed rebuild to leave the game on the official patch, so that I can still play normally.
22. As the operator, I want a failure named as build failed, anchors broke or smoke failed, with a one-line reason and a log path, so that I know whether the farmer code needs a fix.
23. As the operator, I want a high-priority notification on any failure and a quiet history line on success, so that I am disturbed only when needed.
24. As the operator, I want "Check again" to retry a failed rebuild, and a new Game update or a farmer-changing App update to retry it by itself, so that recovery never needs a terminal.
25. As the operator, I want a Game reinstall to show "start the game and accept the update" and nothing else, so that the app never fights the game's own updater.
26. As the operator, I want a way to restore the official patch, so that I can play without the farmer at any time.

### App update
27. As the operator, I want each machine to check for a new app version at service start and once a day, so that both machines stay current without my help.
28. As the operator, I want a new version downloaded and verified at once and installed only when no AFK session runs and the game is closed, so that an update never breaks a night.
29. As the operator, I want a new version that fails to come up to be reverted by itself and never retried, so that a bad release does not leave a machine broken.
30. As the operator, I want a manual rollback button, so that I can return to the previous version.
31. As the operator, I want the farmer patch rebuilt after an App update only when the farmer changed, so that updates do not trigger needless rebuilds.
32. As the operator, I want a failed update check to stay quiet except for a rejected token, so that offline days do not spam me.

### Quarantine
33. As the operator, I want the quarantine screen to show the reason, one line of detail and one next action, so that the morning after a failure is quick.
34. As the operator, I want the attempts and log paths collapsed under the summary, so that diagnostics are there without clutter.

### Install and platform
35. As the operator, I want the same app and the same behaviour on Linux and Windows, so that I learn one tool.
36. As the operator, I want the Windows app to need no Python, bash or admin rights at runtime, so that the machine stays clean.
37. As the operator, I want setup on Windows to warn me if auto-logon or Windows Update active hours would end the night, so that I know the risk before relying on it.
38. As the operator, I want uninstall to remove the service and restore the official patch while keeping my profile, so that removing the app is safe.
39. As the developer, I want a tag to build, test and publish both platforms in CI, so that a release needs no Windows machine.

## Implementation Decisions

### Shape
- One Python 3.13 package with three parts. **core** holds the supervisor, preflight, the Game update states and pipeline, farmer patch build and install, verify, history and the App update apply. **platform** has one Linux and one Windows implementation behind one interface. **gui** is PySide6/QML. There are two entry points: the window and the service. Dependencies are the standard library plus PySide6; OS mechanisms go through `ctypes`, `subprocess` and system tools. Any other dependency is argued in its ticket. (ADR 0006)
- The in-game farmer stays GDScript and is a build input. The `.gd` sources and the save-hook and player injectors are part of the app.
- Every bash script (run, build, install, uninstall, verify, check) is ported to core modules and deleted once the existing pytest scenarios pass against the new modules. There are no Python→bash shims. The Linux farm keeps running on the old code until cutover.
- The C++ window, its build scripts and its pacman package are deleted at cutover. Screens follow the prototype on branch `prototype/gui-shape`; the old QML contributes only components (stat card, log panel).

### platform interface
- One interface carries everything that differs between the OSes:
  - single-instance lock (fcntl on Linux, LockFileEx on Windows);
  - finding the running game process;
  - starting the game in a killable group and killing the whole tree (process group / Job Object);
  - registering and removing the service;
  - desktop notifications;
  - locating the profile;
  - setup warnings;
  - network isolation.
- **Profile location:** the profile is found by its markers (`profile.json` plus `patches/state.json`) under the OS's Godot user-data root, never by folder name. Windows uses `Ragnarok Survivors` and Linux `Midgard Survivors`, and a Game reinstall can rename it.
- **Process arguments** are always passed as a list. Windows PowerShell's string joining split a profile path containing a space (ticket 03).
- **Atomic replace:** status, checkpoint, state and pointer files are written to a temp file and replaced in a single OS operation. Godot's own rename on Windows is not atomic, so the farmer side keeps its existing approach (ticket 01).
- **Network isolation:** on Linux, `unshare -cn` as today (ADR 0002). On Windows v1 there is none, a conscious divergence (deferred ticket 08). Risks to record in the README: the updater's modal prompt can stall a night, and CloudSave can race the farm if the profile is cloud-linked.

### Service
- **Linux:** a systemd user unit, as today.
- **Windows:** a Task Scheduler task at user logon, hidden, restarting on failure, with no elevation.
- The service runs on Windows only while the operator is signed in. It survives a closed window, a locked screen and an off monitor, but not sign-out or reboot.
- The supervisor keeps ADR 0003: it alone decides the terminal outcome. On Windows a hard-exited game reports no usable exit code, so the outcome comes only from the farmer's terminal status.
- The supervisor's policy (backoff, quarantine threshold, fatal reasons) carries over unchanged, plus the Game update additions below.

### Window ↔ service (deferred ticket 09 default)
- The window polls files. These are the existing farmer status and command files, the supervisor's quarantine record, a service state file (alive, idle, rebuilding, updating, farmer unavailable, with reason) and an append-only history file.
- **History file:** one line per session outcome and per Game update or App update event.
- **Commands:** the window writes command files the service consumes: start with character and preset, pause, resume, finish, abort, check again, rollback app, restore official patch. Finish, abort, pause and resume keep ADR 0004 semantics.
- **Liveness:** the service refreshes its state file periodically. A stale state file means "service not running", and the window then offers to start it.

### Game update states (ticket 06)
- Before each attempt, at service start and on each command, the service compares `state.json` with the installed farmer patch info and with the current **Farmer hash**. No hashing of game files is needed for this. The comparison yields one of:
  - **current:** the farmer patch is mounted, its official base matches, and the Farmer hash matches;
  - **Game update:** a different official patch is mounted and the farmer patch is gone;
  - **farmer patch removed or stale:** the same official patch as the info, but the farmer patch is not mounted or its Farmer hash differs;
  - **Game reinstall:** `state.json` is missing or empty.
- **Game update** and **Farmer hash change** both run the pipeline. **Removed** reinstalls the existing pack without rebuilding. **Game reinstall** does nothing automatic and shows "start the game and accept the update".
- The legacy preflight exit 78 stays underneath as a safety net.
- **Game running:** while the game process lives, nothing happens and the state reads "waiting for the game to close". After it exits there is a short grace period, because the updater restarts the game itself.

### Game update pipeline (ticket 06, ADR 0005)
- **Order:**
  1. refresh `official-state.json` from the official state the game just wrote;
  2. build the farmer patch on this machine;
  3. smoke in the sandbox;
  4. install into the real profile;
  5. run the attempt.
- **Build:** GDRE v2.7.4 headless, downloaded on first use, verified against a pinned sha256 and kept in the app data dir. Steps:
  1. extract `save.gdc` and `player.gdc` (patch, then bridge, then base);
  2. decompile with bytecode `ebc36a7`;
  3. inject the save hook;
  4. apply the player patch;
  5. compile the three scripts;
  6. `pck-patch` the official patch;
  7. verify the three files inside the result.

  The build is byte-deterministic and identical on Linux and Windows (ticket 03). It took about 16 s on Windows.
- **Decompile cache:** keyed by every input.
- **Patch info:** records the official patch file, version and sha, the bridge, the bytecode, the farmer API, the Farmer hash and the result sha.
- **Smoke:** the existing one-run verify scenario in a sandbox profile copy, 300 s hard limit, one retry. It passes on:
  - status `done`, not failed;
  - wins ≥ 1 with the last run a victory;
  - kills > 0 and zeny gain > 0;
  - a FINISH log marker;
  - no script errors in the game output.
- On Windows the game output is captured from stdout, not from `godot.log`.
- **Install:** back up state and profile files, replace the pack atomically, set `file` to the farmer patch and `farmer` to 1 (keeping base, bridge and version), then verify the installed hash. A failure restores the backup.
- **Failure outcomes:** a missing injector anchor gives **anchors broke**; any other build error gives **build failed**; a failed smoke gives **smoke failed**.
- **On failure:** the supervisor quarantines at once with reason `anchors_broken`, `build_failed` or `smoke_failed`. The real profile is left untouched on the official patch, and Start is refused.
- **Retry block:** keyed by (official patch sha, Farmer hash). It lifts on "Check again", on a new Game update, or on an App update that changes the Farmer hash. Every other preflight failure and every crash-loop quarantine stays final.
- **Fallback:** none. After a Game update the previous pack is unusable. The orphaned old official patch is left alone.
- **Restore official patch:** restore `state.json` from `official-state.json` and delete the farmer patch. It is refused while the game runs. If the named official file is missing, the operator is told "start the game and accept the update".
- **Session continuity:** a Game update cannot land inside an AFK session (one game per machine, pause keeps the game alive). The pipeline always runs before the first attempt.

### App update (ticket 07, ADR 0007)
- **Source:** a private GitHub repository with Releases. A `v*` tag triggers GitHub Actions on Linux and Windows runners, which run the pytest suites (including `platform` on Windows), build a PyInstaller onedir per OS and publish them with sha256 files.
- **Install layout:** a user-owned versioned directory per machine, under the user data dir on Linux and under local app data on Windows. It holds one directory per version and a `current` pointer. No root and no installer.
- **Update check:** the service checks at start and once a day with a fine-grained read-only token stored in the app's data. The new version is downloaded and verified at once.
- **Switching versions:** the `current` pointer switches in a quiet window (no AFK session, game not running). The new service must write a readiness marker within 60 s: config read, profile found, platform checks passed. Without it the pointer reverts, the version is marked bad and never retried, and a high-priority notification is sent.
- **Retention:** the current and one previous version are kept, and manual rollback switches the pointer.
- **Farmer hash:** the app computes it from its farmer build inputs (the farmer and save-hook sources, the injectors, the farmer API and the bytecode). A change triggers the Game update pipeline even with an unchanged official patch.
- **Data formats:** backward-compatible by default (new fields only), so rollback is always safe. A breaking change is a declared release exception with a `schema` field and a forward migration after a backup; a rollback across it restores the backup.
- **Failed checks:** a failed update check is quiet, and the window shows "updates not checked for N days (reason)". Only a rejected token sends a notification.

### Notifications
- Desktop on both OSes plus the existing optional ntfy.
- **Events:**
  - session fail, quarantine, stop and goal (as today);
  - Game update handled (low priority, only when unattended);
  - build failed, anchors broke, smoke failed (high);
  - App update rolled back (high);
  - token rejected.
- Configuration (ntfy URL) lives in a config file. There is no settings screen.

### Window (ticket 05)
- Four screens: AFK session, History, Updates, Quarantine. There is no settings screen.
- **AFK session:** phase and heartbeat on top, income and the current run below; character and preset pickers (the preset carries location and difficulty, and the window never edits presets); Start, Pause↔Resume, Finish, Abort, with confirmation only on Abort; Start refusal reasons.
- **Updates:** the Game update state and the last outcome; the app version, the last check and rollback.
- **Quarantine:** reason, one line of detail, one next action ("Check again" for the three rebuild reasons, "Start a new session" otherwise); attempts and log paths collapsed.
- Omarchy/Hyprland theming on Linux is a nicety; Windows uses the stock Qt style.

### First install and uninstall
- **First install:** the operator downloads the release archive for the OS once, unpacks it anywhere and runs its setup command. Setup then:
  1. copies itself into the versioned directory;
  2. asks for the read-only token;
  3. registers the service;
  4. on Windows, warns if auto-logon is off or Windows Update active hours do not cover the night.
- **Uninstall:** removes the service, restores the official patch and keeps the profile, logs and history.

## Testing Decisions

- **A good test** drives the app from the outside and asserts on files and outcomes, not on internals. Fakes stand in only for the game and GDRE.
- **Service seam (primary).** Run the service against a temporary profile directory with a fake game (prior art: the fake farmer and the run-script fake game) and a fake GDRE. Feed commands, assert on status, history, quarantine records, Game update states, rebuild outcomes and App update pointer switches, including:
  - the retry block keyed by (official patch sha, Farmer hash);
  - automatic revert when the new version writes no readiness marker;
  - no failure counted for a pre-launch rebuild.

  Port the current supervisor (20 tests) and run-script (16 tests) scenarios to this seam first; they prove parity before bash is deleted. Runs in CI on Linux and Windows.
- **platform seam.** Test each implementation against the real OS on CI runners:
  - lock exclusivity;
  - killing a process tree including grandchildren;
  - profile discovery by markers (including a folder name with a space);
  - service registration in a dry-run mode;
  - atomic replace.
- **Live game (not CI).** The verify scenarios run on a real machine; one-run is also the smoke. The soak stays Linux-only for now.
- **Window.** One offscreen test loads the QML against a fixture data directory and checks that it renders each screen without errors. No logic lives in the window.

## Out of Scope

- Network isolation on Windows (deferred ticket 08; v1 default above).
- A live channel between the window and the service (deferred ticket 09; v1 polls files).
- Comparing rewards per hour by preset or character, and long-term history retention beyond the session list.
- A notification settings screen.
- Running the soak and the other live verify scenarios on Windows.
- Distributing the app to anyone else, syncing profiles between machines, the app downloading or decrypting the official patch, macOS and Android.
- Rewriting the in-game controller.

## Further Notes

- **Cloud linkage.** The Linux profile is CloudSave-linked. Whether gpu-pc uses the same cloud account is unknown (ticket 08, question F1). If it does, the two machines are not independent: the game itself syncs the profile between them, and nightly farms on both machines can conflict through the cloud. Check this before farming on both machines.
- **Stale ADR remark.** The farmer does not read the `offline` config key; ADR 0002's remark about it is stale.
- **Infrastructure dependency.** The home domain behind the tailnet and the self-hosted services has lapsed at the registrar. Nothing in this spec depends on it, but SSH to gpu-pc does.
- **Windows bench facts (ticket 03):**
  - Windows 11 25H2, admin account, no Python, never sleeps on AC;
  - base 0.1.272 versus 0.1.259 on Linux, while the official patch and bridge are byte-identical;
  - the bench scripts in `../gui-windows-updates/assets/` are throwaway.
