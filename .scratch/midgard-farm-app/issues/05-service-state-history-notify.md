# 05: Service state, history and notifications

**What to build:** The service publishes what the window needs: a service state file (alive, idle, waiting for the game, rebuilding, updating, farmer unavailable, with reason) refreshed periodically, and an append-only history with one line per session outcome and per Game update or App update event. Notifications go to the desktop and optional ntfy for the events in the spec.

**Blocked by:** 04.

**Status:** ready-for-agent

- [ ] The state file is refreshed periodically; a stale file is distinguishable from an idle service.
- [ ] Each session terminal outcome appends one history line with totals; the format is backward-compatible by design.
- [ ] Notification events and priorities match the spec; a failing notifier never blocks recovery.
- [ ] The ntfy URL comes from a config file; there is no settings UI.

## Comments

- 2026-11-19 (from ticket 04): commands are JSON files under `commands/` in the app data dir, published with `core.commands.submit(os_, Start(Character(class_id, job_path), preset) | control)`.
  - After a terminal outcome the service stays idle; it writes `logs/supervisor-<session>/outcome.json`, plus `quarantine.json` when quarantined.
  - Notifications go through one `notify(event, message)` hook (ntfy only); add desktop notifications behind it.
  - The state file must expose, from these records, the last outcome, a quarantine (with reason) and refused commands, so the window can show why a Start did nothing.
  - Desktop notifications (`notify-send`) were dropped when the old supervisor was ported; restore them here.
