# Farmer code map

Where the AFK farmer's behaviour lives. Function names, not line numbers: `grep -n '^func <name>' farmer/src/farmer.gd`.

## Run lifecycle (`farmer/src/farmer.gd`)

`_process` drives one phase per frame:

1. `idle` → `_prepare_run`: choose target, snapshot pre-run state, `world.start_run`, checkpoint `run`.
2. `run` → `_tick_run`; the run ends via the game or `_end_run_safe`.
3. `settle` → `_begin_settle` / `_check_settle` until the end screen.
4. `keep` → `_do_keep`: keep, sell the rest, `Save.flush`, checkpoint `settled`.
5. `maint` → `_do_maintenance`, then `_complete_run`: checkpoint `settled` again, `_account_run` (totals, journal `_append_run_log`, `_update_arm`), checkpoint `idle`.
6. Terminal: `_finish(reason)` (verified flush via `_flush_profile_verified`, `phase=done`) or `_fail_session(reason)` (`phase=failed`).

Cross-cutting:

- Status (supervisor contract): `_write_status`, `_totals`.
- Checkpoint and crash recovery: `_write_checkpoint`, `_restore_checkpoint`, `_journal_has`; session identity from `FARMER_SESSION_ID`.
- Operator commands and limits: `_check_command` (claims `user://farmer_command`; legacy `farmer_stop` = finish), `_check_limits` (`max_minutes`, `max_runs`, `stop_after_wins`), both ending in `_request_finish`.
- Movement: `_steer_goal` selects the game's raid/Morroc target. In 0.2.5 both native autopilot and click-to-move aim directly, and the enemy flow field supplies only local direction hints. `_steer_direct` preserves direct movement until progress stops at blocked terrain, then follows a tile route using the player's own map walkability.
- Level-ups: `_draft_player` calls the game's manual-play auto-picker using the saved per-class priorities, caps, fill and ban choices. The farmer keeps the game’s menu automation for other dialogs and preserves the saved manual-play toggle across `start_run`.
- Hell strategy (`hell-rotation` only): `altar_policy: "map-wide"` searches the field, waits to take Baldur until the MVP portal is open, and gives up a channel after five game seconds without progress. `ALTAR_TAKE` and `ALTAR_SKIP` include the raid state and altar instance. `karma_route: "valhalla"` takes the native karma portal after each regular MVP and waits for `VALKYRIE_KILLED` before continuing. During Reginleif's Caída wave `_kite_starfall` runs a continuous arc inside the rim and outside the crystals, leaving every circle's locked landing point without stopping or reversing. Routes log remaining revives and cumulative leaves spent; a refused route logs `KARMA_ROUTE_SKIP`.

## Around the game

- `farmer/tools/supervisor.py`: restart, backoff, quarantine (with run.sh's preflight `detail`), notifications, the single-supervisor lock, the systemd unit (`--print-unit`). Its tests are in `farmer/tests/test_supervisor.py`.
- The app supervisor's run-clock watchdog is independent of `_check_watchdog` in the game. A portal approach is outside the arena and still has the 180-second run-clock deadline even with fresh heartbeats. Inside the arena the deadline is 1200 seconds; Morroc's local run-clock exemption does not reset either supervisor deadline.
- `farmer/run.sh`: preflight (exit 78 = unfixable: game/patch/build, cfg not a JSON object or using keys from `farmer/obsolete_config_keys.json`, profile dir not writable or below `FARMER_MIN_FREE_MB`), the launcher `flock` (the only single-instance guard), network isolation for supervised sessions, backups and known-good. Its tests are in `farmer/tests/test_run_sh.py`.
- Contracts and operator docs: `farmer/README.md` (AFK session, commands, isolation/backup, status). Decisions: `docs/adr/`.

## Verification

- `farmer/tools/check.sh`: static checks plus pytest when tools, tests or scripts are staged. Needs no game.
- `farmer/tools/verify.sh [--scenario…]`: real-game scenarios on a sandbox copy of the profile. Run `./build.sh` first after any `farmer.gd` change. One game per machine: runs queue on `.sandbox/verify.lock`. `--supervised-*` and `--soak=HOURS` run the real supervisor through `tools/drive_supervisor.py`; `tools/soak_check.py` judges a soak (tests: `farmer/tests/test_soak_check.py`).
- `.venv/bin/python -m midgard_farm.verify --scenario one-run` (repeat `--scenario` to select more), `--all` for all supported headless bounded scenarios, or `--soak=HOURS` for the Linux-only soak. Run from the checkout root with the game closed and an app-built farmer patch. If the legacy patch is still mounted, restore the official patch before using the Python verifier. The CLI copies the profile, queues on `.sandbox/verify.lock`, and saves logs and `summary.json` under `.sandbox/verify-*`; `--keep` also retains successful sandbox profiles. The external-kill scenario is Linux-only and reported as skipped by `--all` on Windows. CI uses only fake games.
- `--scenario watch-mode` runs one supervised windowed run using the same Start setting as the AFK switch. Start it from a graphical desktop and observe the game window; the verifier checks that the supervisor finishes without restarting and retains the raw game exit in its `outcome.json`. `--all` stays headless.
- `--scenario blocked-portal` puts the hero and an open MVP portal on opposite sides of an obstruction in Prontera Field. It passes only if the hero enters the native arena; it does not require a boss kill.
- `--scenario valkyrie-drill` forces early sandbox Valhalla fights at D30/37 oaths. It isolates one native ability per encounter and requires ten complete six-mark Caída waves with Doom active, no leaves, and zero contacts, piercing hits or deaths.
- The real profile and the real install (`./install.sh`) are the operator's. Leave them to the operator.
