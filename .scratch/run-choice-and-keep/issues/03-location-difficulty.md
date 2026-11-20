# 03: Location and difficulty chosen in the window

**What to build:** The operator chooses the location (or Automatic) and the difficulty (Automatic, or a fixed level in the location's range) in the window, from the catalog; locked locations are shown but not selectable, and without a catalog only Automatic is offered. Start and Resume carry the run choice; the service writes it into `farmer.cfg`; the window remembers it per machine. Presets lose `stage`, `danger`, `class` and `class_rotate` and become strategy only (ADR 0009); `synx-hell` and `sniper-hell` are deleted; `one-run` stops being selectable and becomes the smoke and verify configuration with an explicit location and difficulty. The farmer validates the choice against the live game at session start and ends the session as a failure naming the field when it is invalid. The current run and history show location and difficulty.

**Blocked by:** 02.

**Status:** resolved

- [x] Start and Resume requests carry the run choice; malformed requests are rejected through the existing rejection path; covered by tests.
- [x] The service writes the run choice into `farmer.cfg`; the preset never contributes location, difficulty or class; a preset containing `stage`, `danger`, `class` or `class_rotate` is refused as unfixable naming the key.
- [x] The window's location and difficulty lists follow the catalog (range follows the location, locked locations disabled, only Automatic without a catalog) and the choice is remembered; covered by GUI tests with fixture catalogs.
- [x] A choice changed while paused applies from the next run after Resume.
- [x] The preset list no longer offers `one-run`, `synx-hell` or `sniper-hell`; smoke and verify still run with an explicit location and difficulty.
- [x] A verify scenario: a fixed location and difficulty appear as the run's target in status and journal; another: a locked location ends the session as a failure naming the location, and the supervisor does not retry it.
- [x] The AFK current-run view and history show location and difficulty.
- [x] Static checks and the pytest suite pass.

Real verification on patch 0.2.5: `run-choice`, `run-choice-resume`,
`invalid-location`, `invalid-difficulty`, and `one-run` passed. The profile
had every location unlocked, so `invalid-location` uses an unknown ID.

Spec: [`../spec.md`](../spec.md).
