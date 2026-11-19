# 08: Window: AFK session screen

**What to build:** A PySide6/QML window shows the AFK session screen: phase and last heartbeat on top, income and the current run below, character and preset pickers (last choice remembered), Start, Pause/Resume, Finish and Abort (confirmation only on Abort, naming what is lost), and the reason when Start is refused. Closing the window leaves the session running; a dead service is shown as such with an offer to start it.

**Blocked by:** 05.

**Status:** resolved

- [x] The window only reads the status, state and history files and writes command files; it holds no farm logic.
- [x] Abort shows one confirmation; no other action asks.
- [x] An offscreen test loads the QML against a fixture data directory and renders without errors.
- [x] Layout follows the prototype on branch `prototype/gui-shape`; stat card and log panel components may be lifted from the old QML.

## Comments

- 2026-11-20: Done in `c4a00dd` and `b47d73c` (Fusion style pinned; Windows font dir for the offscreen tests). CI is `f1b4349`, with Qt runtime libs on Ubuntu; run 44607943474 passed on Linux and Windows.
  - Entry point: `midgard-farm`.
  - Characters come from `farmer/targets.json`. `profile.json` is AES-encrypted and the window does not decode it.
  - Polling runs on a worker thread.
  - Finish and Abort are enabled during startup and restart backoff.
  - "Start service" runs `systemctl --user start midgard-farm.service` on Linux or the `Midgard Farm` scheduled task on Windows.
  - Independent review: CHANGES_REQUIRED; the major and the minors are fixed. Moved to 09: the session log path helper. Moved to 11: catalog packaging.
  - Not yet seen by the operator against real data; native Windows rendering is untested.
