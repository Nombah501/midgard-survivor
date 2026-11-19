# 05: Service state, history and notifications

**What to build:** The service publishes what the window needs: a service state file (alive, idle, waiting for the game, rebuilding, updating, farmer unavailable, with reason) refreshed periodically, and an append-only history with one line per session outcome and per Game update or App update event. Notifications go to the desktop and optional ntfy for the events in the spec.

**Blocked by:** 04.

**Status:** resolved

- [x] The state file is refreshed periodically; a stale file is distinguishable from an idle service.
- [x] Each session terminal outcome appends one history line with totals; the format is backward-compatible by design.
- [x] Notification events and priorities match the spec; a failing notifier never blocks recovery.
- [x] The ntfy URL comes from a config file; there is no settings UI.

## Comments

- 2026-11-19 (from ticket 04): commands are JSON files under `commands/` in the app data dir, published with `core.commands.submit(os_, Start(Character(class_id, job_path), preset) | control)`.
  - After a terminal outcome the service stays idle; it writes `logs/supervisor-<session>/outcome.json`, plus `quarantine.json` when quarantined.
  - Notifications go through one `notify(event, message)` hook (ntfy only); add desktop notifications behind it.
  - The state file must expose, from these records, the last outcome, a quarantine (with reason) and refused commands, so the window can show why a Start did nothing.
  - Desktop notifications (`notify-send`) were dropped when the old supervisor was ported; restore them here.
- 2026-11-20: Done in `3adfade` and `0abd4ad`; CI run 44600114868 passed on Linux and Windows.
  - Contract:
    - `state.json` v1: kind, reason, updated_at, refresh_interval, session_id, farmer_phase, last_heartbeat, last_outcome, quarantine {reason, detail, next_action}, command_refusals. `read_state(os_)` reports STALE when the file is older than 3× refresh.
    - `history.jsonl` v1: a `session` row with totals that mirror `farmer/tools/summary.py`, plus `append_event(os_, "game_update" | "app_update", …)`. Readers skip unknown fields and a torn last line.
    - `Notifier`: desktop (`notify-send`, or a Windows toast via a hidden PowerShell process with no console) plus ntfy from `config.json` `{"ntfy_url": …}`. Priorities follow the spec; the drain is bounded.
  - `Platform.read_shared` retries Windows sharing violations while a file is replaced; every reader of replaced files uses it.
  - Independent review: CHANGES_REQUIRED; the major and all minors are fixed.
  - The window (08) must read a session quarantine from its log dir; the top-level `quarantine.json` is only the startup quarantine.
  - Windows toast delivery is still unverified on real Windows (ticket 10).
