# 08: Window: AFK session screen

**What to build:** A PySide6/QML window shows the AFK session screen: phase and last heartbeat on top, income and the current run below, character and preset pickers (last choice remembered), Start, Pause/Resume, Finish and Abort (confirmation only on Abort, naming what is lost), and the reason when Start is refused. Closing the window leaves the session running; a dead service is shown as such with an offer to start it.

**Blocked by:** 05.

**Status:** ready-for-agent

- [ ] The window only reads the status, state and history files and writes command files; it holds no farm logic.
- [ ] Abort shows one confirmation; no other action asks.
- [ ] An offscreen test loads the QML against a fixture data directory and renders without errors.
- [ ] Layout follows the prototype on branch `prototype/gui-shape`; stat card and log panel components may be lifted from the old QML.
