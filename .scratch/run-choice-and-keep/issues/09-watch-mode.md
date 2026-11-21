# 09: Watch mode: see the game while the farmer plays

**What to build:** A remembered "Show game window" switch on the AFK screen. When it is on, the service launches the game windowed instead of headless, so the operator can watch the farmer play and spot weaknesses; the farmer plays exactly as it does headless (same speed, autopilot, maintenance). The switch is part of the session settings carried by Start; it takes effect at the next game launch (a Resume does not relaunch the game, so it applies after the next restart). The `display` key leaves presets (the window owns it, ADR 0009) and is refused in a preset like other obsolete keys; the existing `FARMER_DISPLAY` environment override keeps working for development. Closing the game window by hand during a session is treated like any other game exit (the supervisor's existing restart rules), and the window's help text says so.

**Blocked by:** 08.

**Status:** ready-for-agent

- [ ] The switch is on the AFK screen, off by default, remembered, editable when Start is possible; covered by GUI tests.
- [ ] Start carries it into `farmer.cfg` `display`; the launcher runs the game windowed exactly when it is on; presets no longer contain `display` and a preset containing it is refused naming the key; covered by service launch tests.
- [ ] On Linux the windowed game runs under the supervised session's network isolation (the display socket must stay reachable); a real launch with the switch on shows the game window and completes one run (operator-visible check, or a screenshot from the verify run).
- [ ] Static checks, mypy (Linux and Windows targets as in `.githooks/pre-push`), the pytest suites pass.

Spec: [`../spec.md`](../spec.md).
