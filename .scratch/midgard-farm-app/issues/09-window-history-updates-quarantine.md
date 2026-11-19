# 09: Window: History, Updates and Quarantine screens

**What to build:** The remaining three screens. History lists sessions and update events, with the last night expandable to totals, rewards per hour and materials. Updates shows the Game update state and last outcome, and the app version, last check and rollback. Quarantine shows the reason, one line of detail and one next action (Check again for the three rebuild reasons, otherwise Start a new session), with attempts and log paths collapsed.

**Blocked by:** 07, 08.

**Status:** resolved

- [x] Every Game update state and outcome from the spec has its wording on the Updates screen.
- [x] Check again and Restore official patch are reachable from the window.
- [x] The offscreen QML test covers all four screens with fixture data.

## Comments

- 2026-11-20 (review of ticket 08):
  - The window re-encodes the service's session log layout (`afk-<hex>`, `logs/supervisor-<id>/quarantine.json`) to find a session's quarantine record. Replace this with one public core helper (e.g. `session_log_dir(os_, session_id)`, or the record path published in `state.json`) and use it from the Quarantine screen.
  - A Start can now say "the preset decides" (`Start.character = None`, from ticket 14). Consider offering it in the character picker.
  - "Restore official patch" needs a command the service consumes (only `check_again` exists). Add it with the service refusing while the game runs, and wire it into `farmer_patch.restore`.
- 2026-11-20: Done in `997209d` and `908adc8` (review fixes). CI run 44619850522 passed on Linux and Windows.
  - `restore_official` is consumed only when idle. It is refused, and the refusal recorded, while the game runs or a session is active. After a restore the official patch stays mounted until Start or Check again; `state.json` carries `keep_official` and `last_restore`. A restore appears in history as a `game_update` row with `action=restore_official`.
  - `supervisor.session_log_dir` is used by the window and the verify driver.
  - 'Preset decides' is in the character picker.
  - The app part of the Updates screen shows the version and 'No update check yet' until ticket 13.
  - A test pins `gui/_resources.py` to `Main.qml` byte for byte. Regenerate with `pyside6-rcc` after any QML change. `.gitattributes` keeps `gui/*.qml` LF.
  - Independent review: CHANGES_REQUIRED (the bundle drift test); fixed.
