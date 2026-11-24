# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop

Native desktop window built with Qt Quick (PySide6, QML in `src/midgard_farm/gui/Main.qml`), shipped for Linux x86_64 and Windows x86_64. Not a web page and not a mobile app.

## Users

One person: the Operator, who owns the Midgard Survivors profile and runs the farm on his own PC. He knows the game deeply (classes, locations, difficulty, oaths, legendaries, MVPs) and the farm's vocabulary (see `GLOSSARY.md`). He uses the window both to set up a session before starting it and to glance at a running session later; neither dominates.

## Product Purpose

Midgard Farm runs Midgard Survivors unattended (AFK) for hours through a background service and a farmer patch. The window does not play; it lets the Operator choose the run (character, mode, location, difficulty, oaths, route, wishlist, maintenance switches), start/pause/finish/abort the session, see what the farm earns and did (history, last night), keep the game and the App updated, and understand quarantine when something is refused. Success: setup is fast and unambiguous, and one look tells whether the farm is working and what it earned.

## Positioning

A personal tool that plays the game exactly as it is, never changes the Operator's prepared character (ADR 0008) and lets the window own the whole run choice, including a fixed Mode and the karma Route (ADR 0009, ADR 0011). It never submits farmer runs online.

## Operating Context

- Linux: the window sits on a large monitor next to other windows; the service runs as a systemd user unit. Windows: scheduled task "Midgard Farm".
- The window may also be small (laptop or a narrow tile); it must fit without horizontal overflow and keep primary actions reachable.
- Closing the window leaves the AFK session running in the background service.
- Typical rhythm: configure and start in the evening, glance during the night or next morning, read history.

## Capabilities and Constraints

- Screens today: AFK session, History, Updates, Quarantine; abort confirmation dialog.
- Controls are addressed by `objectName` in GUI tests (`tests/test_gui.py`); renamed or removed object names break tests and must be migrated with them.
- QML resources are compiled into `src/midgard_farm/gui/_resources.py` with `pyside6-rcc`; regenerate after QML edits.
- Copy is English; game terms (Location, Difficulty, Oath, Mode, Route, Wishlist, Keep, Valkyrie, MVP) follow `GLOSSARY.md`.
- Must render identically under Linux and Windows Qt styles; no web fonts or network assets.

## Evidence on Hand

- Real game data reaches the window through the catalog: characters, locations, difficulties, oaths, legendary items. No game art is bundled in the App; do not invent game art or claims.
- Screenshots of the current window (2026-11-22) show broken layout: content overflowing the card's right edge, the oath points counter overlapping a switch label, mixed switch/button rows, empty metrics occupying space.

## Product Principles

1. The farm's state is the headline: whether it runs, what phase, what it earned.
2. Setup reads like the game's own run choice: same names, same order, no hidden strategy knobs.
3. Nothing the window shows may overflow, overlap or hide a primary action at any window size the Operator uses.
4. Safety is visible: destructive actions (abort) confirm the loss; refusals explain the reason next to the action.
