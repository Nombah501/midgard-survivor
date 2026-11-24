# Midgard Farm

## Install from a release

Download and unpack the archive for your OS from the public [GitHub Releases](https://github.com/Nombah501/midgard-survivor/releases). Open a normal terminal (no `sudo` or Administrator) in the unpacked `midgard-farm` folder and run setup:

| Linux | Windows PowerShell |
| --- | --- |
| `./midgard-farm-setup` | `.\midgard-farm-setup.exe` |

Setup installs the app under `versions/<release>/` in `$XDG_DATA_HOME/midgard-farm` (default `~/.local/share/midgard-farm`) or `%LOCALAPPDATA%\MidgardFarm` and prints the installed window's path. It registers a systemd user unit on Linux and a hidden, least-privilege logon task on Windows. Both run the stable launcher in `bin/`, which reads `current` on every start. Only rerunning setup refreshes the launcher; stop the service first if setup needs to replace it.

To inspect the service definition without installing or registering it, run setup with `--print-registration`.

Open the installed `midgard-farm` window and use **Start service** for the first session; setup does not start it. On Windows, sign in and keep the machine awake. Setup only reads the auto-logon setting and checks Windows Update active hours against 22:00–06:00 local time; it does not change either setting or guarantee against restarts.

If the legacy checkout mounted the farmer patch on Linux, restore the official patch with the legacy `uninstall.sh` before starting the new service. The new app expects its own `patches/official-state.json` in the game profile and will not guess from legacy backups.

## AFK settings

Pick **Mode** and **Route** under **Run choice**. *Endless until the final boss* plays each run to the game's finale; *Short runs (until the MVP)* ends after the map MVP. **Route** picks the karma portal after each regular MVP in Endless: *Valhalla*, *Hel* (the farmer then also takes Hel altars) or *Random each run*. Towers ignore both. Preparing the character (gear, cards, stats, skills) is always the Operator's job; the farmer plays it as it is.

Open **Maintenance** on the **AFK session** screen to choose Kafra/Sage upgrades, spare-card fusion, Star Smith for unworn items, and storage cleanup. Upgrades and fusion start enabled; Star Smith and cleanup start disabled. The window remembers these choices on this machine and applies them on **Start** or **Resume**.

**Show game window** on the **AFK session** screen is off by default and remembered on this machine. It applies the next time the game launches; changing it before **Resume** does not reopen the running game. The farmer plays the same way and Linux still isolates its network. Closing the game window is a game exit and may trigger a restart; use **Finish** to settle the current run and stop normally. Developers can still force watch mode with `FARMER_DISPLAY=1` in the launcher's environment.

## App updates

The background service checks the signed stable channel at startup and every 24 hours. No GitHub token is needed. The service verifies the manifest's signature, expiry and sequence, then verifies the archive's size and SHA-256 before staging it. It waits for the AFK session to reach its terminal outcome and for the game to close, then switches `current` and restarts the service. If the selected service does not report ready within 60 seconds, an independent watchdog from the previous release restores it and excludes the failed version from future checks.

If systemd confirms that it refused the first start and the new service never ran, the watchdog restores the previous release without blacklisting the candidate. Windows Task Scheduler errors reported directly at restart are handled the same way. After Windows accepts a restart request, a missing readiness marker still counts as a failed release: the task's last-run result alone does not identify this handoff reliably.

In **Updates**, see the selected version, the latest signed release and its changelog, and the result of the last check. **Check for updates** asks the running service to check now; it is separate from the Game update check. Use **Roll back to …** to queue a rollback when a previous release is available, or run `midgard-farm-service rollback-app` (`midgard-farm-service.exe rollback-app` on Windows). Start the window from the selected version's folder after an App update. The game preparation pipeline rebuilds the farmer patch if the selected version's Farmer hash differs.

For the first signed-channel release, revoke any old release PAT on GitHub and install the new archive manually using setup above. If an App update is still pending, restart the service to let it resume. If both the watchdog crashed and the selected service cannot start, run setup from the **previous** release's folder under `versions/` (or unpack its archive and run setup from there), then use **Start service**. Keep `app-update-sequence.json`: rolling back the local app does not lower the update channel's replay protection. See the [release notes](CHANGELOG.md) and [signed channel setup](docs/adr/0010-signed-app-update-channel.md).

## Doctor and farmer patch repair

Open **Health** in the window and press **Run checks**, or run `python -m midgard_farm.doctor` from a checkout with Midgard Farm installed. Doctor checks the game executable, profile, official and farmer patches, pinned GDRE cache, network isolation, service registration and heartbeat, free space on both volumes, ntfy configuration, the signed App update channel, and current quarantine. Each check shows a status and a suggested next step; the CLI exits `1` if any check fails (`0` if there are only successes or warnings). It reads the patch files to verify their digests; it does not contact servers, send notifications, launch the game, or change files. Checks run only when asked, never during polling.

If Doctor reports a missing official patch, open the game and accept its update, then close it. If the farmer patch is missing or its digests do not match, finish any AFK session (including a paused session), close the game, and press **Repair farmer pack** in **Health** (or **Game update → Check again**) while the service is running and idle. Leave the game closed and don't start another AFK session until the check completes. The service verifies the digests on this explicit check (not on every poll), then reinstalls a matching built patch or rebuilds and smoke-tests a replacement on a sandbox copy. Repair only changes the patch installation; it does not edit or restore the game saves.

## Uninstall

Finish any AFK session, close the game and window, and run setup with `--uninstall` from the installed version or the unpacked archive:

| Linux | Windows PowerShell |
| --- | --- |
| `./midgard-farm-setup --uninstall` | `.\midgard-farm-setup.exe --uninstall` |

This stops and removes the service and restores the official patch without deleting the game profile, logs or history. If it reports a missing official patch, open the game and accept its update, close it, and rerun uninstall. To also remove the installed app files after successful uninstall, delete `bin/`, `versions/` and `current` from the app data directory; leave the rest in place to keep your data and the saved update sequence.

## Windows development checkout

Run from a checkout with Python 3.13. No app installer, bash, or administrator rights are needed. In an **unelevated** PowerShell at the checkout root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Set-Location src
..\.venv\Scripts\python.exe -m midgard_farm.service --print-task
..\.venv\Scripts\python.exe -m midgard_farm.service --register
schtasks.exe /Run /TN 'Midgard Farm'
..\.venv\Scripts\python.exe -c 'from midgard_farm.gui import main; raise SystemExit(main())'
```

`--print-task` (or `--register --dry-run`) only renders the task. Registration uses the current user's interactive session and runs the service at logon without a console. The task retries a failure up to three times, one minute apart. You can close the app window or lock the screen; stay signed in and keep the machine awake. If you move the checkout or its virtual environment, register again. To remove the registration, finish any AFK session, stop the task with `schtasks.exe /End /TN 'Midgard Farm'` if it is running, then run `..\.venv\Scripts\python.exe -m midgard_farm.service --unregister` from `src`.

With the service running, start `MidgardSurvivors.exe` manually once, accept any official update, then close the game. The service remembers its location. `GAME_DIR` (when set in the service's environment) overrides the absolute `game_dir` in `%LOCALAPPDATA%\MidgardFarm\config.json`; both override the remembered location. For example: `{"game_dir": "C:\\Games\\Midgard Survivors"}`. Once the service is ready, select a character and preset in the window and start an AFK session.

**Windows v1 does not isolate the game from the network.** An official updater prompt can stall an unattended session. On a CloudSave-linked profile, a cloud pull can restart the game or a conflict dialog can block it. The Linux profile is CloudSave-linked; check whether gpu-pc uses the same cloud account before farming on both machines. Do not run simultaneous farms against the same cloud profile.

### Verify on gpu-pc

1. **Compare builds.** On both machines, use the same checkout revision and a copied profile with the same official patch and bridge. If a farmer patch is mounted, the copy must also have its `patches/official-state.json`. Use matching base packs if extraction falls back to the base. Never run this against the live Linux profile. Save the following as `parity.py` in the checkout's `src` directory on each machine. From `src`, run it with the checkout's Python 3.13 and the arguments `parity.py "<copied profile>" "<game directory>"`:

   ```python
   import os
   import sys
   import tempfile
   from pathlib import Path
   from midgard_farm.core.farmer_patch import build
   from midgard_farm.platform import current

   profile, game_dir = map(Path, sys.argv[1:])
   os.environ["GAME_DIR"] = str(game_dir.resolve())
   with tempfile.TemporaryDirectory() as data:
       os.environ["LOCALAPPDATA" if sys.platform == "win32" else "XDG_DATA_HOME"] = data
       result = build(current(), profile.resolve())
       for name in ("patch_sha256", "bridge_sha256", "farmer_hash", "result_sha256"):
           print(name, getattr(result, name))
   ```

   All four hashes must match. This only builds; it does not install a patch.

2. **Verify discovery.** In a normal unelevated Windows session with no `GAME_DIR` or `game_dir` override, register and start `Midgard Farm` as above. Start the game once on gpu-pc, accept any official update, and close it. In PowerShell, `Get-Content "$env:LOCALAPPDATA\MidgardFarm\game-executable.txt"` must show the correct absolute exe path.

3. **Run three supervised runs.** Use an unlinked or independent gpu-pc profile. When the service is ready, run this from `src` in PowerShell:

   ```powershell
   @'
   from midgard_farm.core.commands import Character, SessionSettings, Start, submit
   from midgard_farm.platform import current

   print(submit(current(), Start(Character("swordsman", 0), SessionSettings("prontera", 1, mode="short"))))
   '@ | ..\.venv\Scripts\python.exe -
   ```

   Close the window after the first run starts. When the third run has started, request **Finish** the same way with `submit(current(), "finish")`. Under `%LOCALAPPDATA%\MidgardFarm`, the newest `logs\supervisor-*\outcome.json` must report `kind: finished`, `reason: finish`, and `totals.runs: 3`. Check the matching entry in `history.jsonl`, a completion toast, and that `Get-Process MidgardSurvivors -ErrorAction SilentlyContinue` returns nothing. The matching farmer terminal status, not the Windows game exit code, proves the finish.
