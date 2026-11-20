# 16: Supervisor restarts a run whose game time stops

**What to build:** The supervisor treats a run that makes no progress as stalled, independently of the farmer's own watchdog. In phase `run`, if the status file's `game.time` has not advanced for a stall window (default 3 minutes, well above the farmer's 45 s `RUN_STALL` escalation, so the farmer gets the first chance), the attempt ends with reason `run_stalled` and follows the crash policy (ADR 0001: the run is aborted, the session restarts). The window and history show the reason.

Background: on 2026-11-19 a run sat at t=640 with no enemies for 6.5 h. The farmer's watchdog only tracked the engine clock and the supervisor only the heartbeat, so nothing reacted. The farmer side is fixed in `54cb7f0` (`RUN_STALL`); this ticket is the second, independent line. Evidence: `.sandbox/incident-20261120-stall/`.

**Blocked by:** 04.

**Status:** resolved

- [x] A fake game with a fresh heartbeat and frozen `game.time` in phase `run` ends the attempt as `run_stalled` after the stall window, at the service seam.
- [x] Pauses, settle/keep/maint, raids within their own window and endless boss fights with advancing time never trigger it.
- [x] `run_stalled` counts towards the crash-loop quarantine like other attempt failures.
- [x] `midgard_farm.health` and the supervisor agree on what "stalled" means (one shared definition).

## Comments

- 2026-11-20 — Implemented the shared run-progress watch, a longer raid window, crash-policy recovery and quarantine, and reason display in the window and history. Health uses the live supervisor timing when available and labels its fallback observations unconfirmed. Verified with fake games and both platform type checks. No real-machine check is required to close the ticket; the provisional 20-minute raid window has not been calibrated against a real raid.
- Full offscreen suite timed out before summary; its only visible failure mapped to the onedir aliased-extraction smoke test, outside this ticket's scope.
- 2026-11-20 — Review follow-up: health now uses same-boot monotonic progress timing and the supervisor's configured heartbeat timeout. Unmatched clock observations are unconfirmed.
