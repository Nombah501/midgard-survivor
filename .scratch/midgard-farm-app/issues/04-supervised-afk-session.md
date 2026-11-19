# 04: Supervised AFK session in the service, with commands

**What to build:** An AFK session runs under the service with today's supervisor policy (heartbeat, backoff, quarantine, terminal outcome per ADR 0003). The operator controls it with start (character + preset), pause, resume, finish and abort through command files. The systemd user unit runs the new service.

**Blocked by:** 02.

**Status:** ready-for-agent

- [ ] Every scenario of the current supervisor test suite is ported to the service seam and passes.
- [ ] Start takes a character and a preset; pause/resume/finish/abort keep ADR 0004 semantics.
- [ ] The terminal outcome comes from the farmer's status, never from the exit code alone.
- [ ] The generated systemd user unit starts the new service; a real overnight session on Linux completes under it.
- [ ] The old supervisor stays in place until cutover (15).

## Comments

- 2026-11-19 (from ticket 02): one attempt is `midgard-farm-service launch [preset] --session-id ID` (`core/launch.py`, `core/preflight.py`, `core/backup.py`). Exit 78 means a preflight or isolation failure (quarantine, no retry); exit 1 means busy or transient.
  - On INT/TERM/HUP/QUIT the attempt writes `farmer_stop`, allows `SHUTDOWN_GRACE_SECONDS` = 45 s (legacy `stop_grace`), then kills the tree. A forced stop never publishes Known-good.
  - The unit's `TimeoutStopSec` (90 s) must stay above that grace.
  - Known-good: generations behind the `backups/known-good/current` pointer.
  - Test gap: the forced-stop test covers manual launches only. Add a supervised one (forced stop must not publish Known-good).
