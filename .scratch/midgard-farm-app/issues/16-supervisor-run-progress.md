# 16: Supervisor restarts a run whose game time stops

**What to build:** The supervisor treats a run that makes no progress as stalled, independently of the farmer's own watchdog. In phase `run`, if the status file's `game.time` has not advanced for a stall window (default 3 minutes, well above the farmer's 45 s `RUN_STALL` escalation, so the farmer gets the first chance), the attempt ends with reason `run_stalled` and follows the crash policy (ADR 0001: the run is aborted, the session restarts). The window and history show the reason.

Background: on 2026-11-19 a run sat at t=640 with no enemies for 6.5 h. The farmer's watchdog only tracked the engine clock and the supervisor only the heartbeat, so nothing reacted. The farmer side is fixed in `54cb7f0` (`RUN_STALL`); this ticket is the second, independent line. Evidence: `.sandbox/incident-20261120-stall/`.

**Blocked by:** 04.

**Status:** ready-for-agent

- [ ] A fake game with a fresh heartbeat and frozen `game.time` in phase `run` ends the attempt as `run_stalled` after the stall window, at the service seam.
- [ ] Pauses, settle/keep/maint, raids and endless boss fights with advancing time never trigger it.
- [ ] `run_stalled` counts towards the crash-loop quarantine like other attempt failures.
- [ ] `midgard_farm.health` and the supervisor agree on what "stalled" means (one shared definition).
