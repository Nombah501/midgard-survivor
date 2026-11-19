# 09: Window: History, Updates and Quarantine screens

**What to build:** The remaining three screens. History lists sessions and update events, with the last night expandable to totals, rewards per hour and materials. Updates shows the Game update state and last outcome, and the app version, last check and rollback. Quarantine shows the reason, one line of detail and one next action (Check again for the three rebuild reasons, otherwise Start a new session), with attempts and log paths collapsed.

**Blocked by:** 07, 08.

**Status:** ready-for-agent

- [ ] Every Game update state and outcome from the spec has its wording on the Updates screen.
- [ ] Check again and Restore official patch are reachable from the window.
- [ ] The offscreen QML test covers all four screens with fixture data.

## Comments

- 2026-11-20 (review of ticket 08):
  - The window re-encodes the service's session log layout (`afk-<hex>`, `logs/supervisor-<id>/quarantine.json`) to find a session's quarantine record. Replace this with one public core helper (e.g. `session_log_dir(os_, session_id)`, or the record path published in `state.json`) and use it from the Quarantine screen.
  - A Start can now say "the preset decides" (`Start.character = None`, from ticket 14). Consider offering it in the character picker.
  - "Restore official patch" needs a command the service consumes (only `check_again` exists). Add it with the service refusing while the game runs, and wire it into `farmer_patch.restore`.
