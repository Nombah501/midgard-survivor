# 07: All unlocked locations in turn

**What to build:** The operator can pick "All locations in turn" as the location. Each run of the AFK session then goes to the next unlocked location in the game's catalog order, wrapping around after the last one; the difficulty and oaths chosen in the window apply to every run. Example: fixed difficulty 30 with every oath at its top rank (37 points) cycles Prontera Field → Payon Forest → … → Thor and starts again. A fixed difficulty must be valid for every unlocked location, so the window offers only the levels inside all of their ranges; Automatic difficulty keeps today's adaptive choice per location. After a crash or restart within the session the rotation continues where it left off, not from the first location. Locked locations are skipped. Resume may switch into or out of rotation like any other location change.

**Blocked by:** 01–06 (done).

**Status:** resolved

- [x] The window's location list offers "All locations in turn" (with a catalog); the difficulty list then offers Automatic plus only levels valid for every unlocked location; the choice is remembered and carried by Start and Resume; covered by GUI tests.
- [x] Start/Resume validate the new location value; malformed values are rejected; covered by tests.
- [x] The farmer picks the next unlocked location per run in catalog order, wraps around, skips locked ones, and continues after a restart within the session; a fixed difficulty outside any unlocked location's range ends the session as `invalid_difficulty` naming it, without retry.
- [x] Oaths still apply only at fixed difficulty 30 and are passed per run for every location in the rotation.
- [x] Status, journal and history show each run's actual location.
- [x] A real verify scenario with rotation over at least two runs shows consecutive runs at consecutive unlocked locations in catalog order, with the chosen fixed difficulty.
- [x] Static checks, mypy for Linux and Windows targets (as in `.githooks/pre-push`), the pytest suites and the touched verify scenarios pass.

Sandbox verification on patch 0.2.5 passed: `location-rotation` completed 24
runs at difficulty 30, including an attempt restart and a full wrap;
`location-rotation-resume`, `invalid-rotation-difficulty`, `run-choice`, and
`oaths` also passed.

Spec: [`../spec.md`](../spec.md). This extends ADR 0009: rotation is a run choice the window owns; the spec's former out-of-scope line on per-run rotation of location no longer applies.
