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

## Around the game

- `farmer/tools/supervisor.py`: restart, backoff, quarantine (with run.sh's preflight `detail`), notifications, the single-supervisor lock, the systemd unit (`--print-unit`). Its tests are in `farmer/tests/test_supervisor.py`.
- `farmer/run.sh`: preflight (exit 78 = unfixable: game/patch/build, cfg not a JSON object, profile dir not writable or below `FARMER_MIN_FREE_MB`), the launcher `flock` (the only single-instance guard), network isolation for supervised sessions, backups and known-good. Its tests are in `farmer/tests/test_run_sh.py`.
- Contracts and operator docs: `farmer/README.md` (AFK session, commands, isolation/backup, status). Decisions: `docs/adr/`.

## Verification

- `farmer/tools/check.sh`: static checks plus pytest when tools, tests or scripts are staged. Needs no game.
- `farmer/tools/verify.sh [--scenario…]`: real-game scenarios on a sandbox copy of the profile. Run `./build.sh` first after any `farmer.gd` change. One game per machine: runs queue on `.sandbox/verify.lock`. `--supervised-*` and `--soak=HOURS` run the real supervisor through `tools/drive_supervisor.py`; `tools/soak_check.py` judges a soak (tests: `farmer/tests/test_soak_check.py`).
- `.venv/bin/python -m midgard_farm.verify --scenario one-run` (repeat `--scenario` to select more), `--all` for all supported bounded scenarios, or `--soak=HOURS` for the Linux-only soak. Run from the checkout root with the game closed and an app-built farmer patch. If the legacy patch is still mounted, restore the official patch before using the Python verifier. The CLI copies the profile, queues on `.sandbox/verify.lock`, and saves logs and `summary.json` under `.sandbox/verify-*`; `--keep` also retains successful sandbox profiles. The external-kill scenario is Linux-only and reported as skipped by `--all` on Windows. CI uses only fake games.
- The real profile and the real install (`./install.sh`) are the operator's. Leave them to the operator.
