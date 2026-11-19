# Midgard Survivor Farmer

A controller that plays real Midgard Survivors runs unattended. The glossary distinguishes the game's own concepts from the farmer's session and supervision concepts.

## Language

**AFK session**:
A continuous period in which the farmer runs without human intervention, from supervisor start to a terminal outcome.
_Avoid_: farm job, bot session

**Run**:
One game run from its start to the end screen, including settlement.
_Avoid_: game, match, attempt

**Settlement**:
The game's banking of a run's rewards, which happens before keep and maintenance.
_Avoid_: payout, reward phase

**Keep**:
The end-screen choice of which offered items to retain; distinct from settlement.
_Avoid_: loot, drop

**Maintenance**:
Between-run town actions such as upgrades, card fusion, loadout and pet selection.
_Avoid_: town phase, chores

**Finish**:
A request to complete the current run's settlement, keep and maintenance, then stop.
_Avoid_: stop, quit

**Abort**:
A request to stop without optional keep; only effects the game has already banked remain.
_Avoid_: cancel, kill

**Pause**:
A request to complete the current run and stop starting new runs until resumed.
_Avoid_: hold, suspend

**Supervisor**:
The external process that starts, monitors, restarts and stops the farmer and owns the terminal outcome.
_Avoid_: watchdog, launcher

**Heartbeat**:
Periodic evidence that the farmer loop is alive; it does not prove that the run is progressing.
_Avoid_: health check, ping

**Checkpoint**:
Persisted session and run facts needed to reconcile after a crash; not a game save.
_Avoid_: save, snapshot

**Run ID**:
A stable identifier for one run, used to make settlement and reporting idempotent.
_Avoid_: run number, index

**Terminal outcome**:
The final state of an AFK session: clean finish, stop, failure or quarantine.
_Avoid_: result, exit status

**Quarantine**:
The supervised state after repeated failures in which automatic restart stops and diagnostics are preserved.
_Avoid_: crash loop, backoff

**Known-good backup**:
A profile snapshot verified as restorable, not merely the newest file.
_Avoid_: backup, copy

**Official patch**:
The game developer's content patch that the game itself downloads and mounts on top of the base game.
_Avoid_: update file, game patch

**Farmer patch**:
A copy of the current official patch with the farmer added; it is mounted instead of the official patch.
_Avoid_: mod, pack, farmer build

**Farmer hash**:
The fingerprint of everything the farmer patch is built from on the app side; when it changes, the farmer patch must be rebuilt even if the official patch did not change.
_Avoid_: farmer version, app version

**Game update**:
A new official patch replacing the previous one, which also removes the farmer patch from the game.
_Avoid_: update, patch change

**Game reinstall**:
A new build of the game itself that wipes every installed patch, official and farmer alike; distinct from a game update.
_Avoid_: new build, reinstall update

**App update**:
A new version of the farmer application itself, independent of game updates.
_Avoid_: update, upgrade

**Operator**:
The person who runs AFK sessions on their own machines; the only intended user of the application.
_Avoid_: user, player
