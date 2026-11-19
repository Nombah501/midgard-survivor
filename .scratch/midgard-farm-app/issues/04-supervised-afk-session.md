# 04: Supervised AFK session in the service, with commands

**What to build:** An AFK session runs under the service with today's supervisor policy (heartbeat, backoff, quarantine, terminal outcome per ADR 0003). The operator controls it with start (character + preset), pause, resume, finish and abort through command files. The systemd user unit runs the new service.

**Blocked by:** 02.

**Status:** ready-for-human (overnight run under the new unit, at cutover)

- [x] Every scenario of the current supervisor test suite is ported to the service seam and passes.
- [x] Start takes a character and a preset; pause/resume/finish/abort keep ADR 0004 semantics.
- [x] The terminal outcome comes from the farmer's status, never from the exit code alone.
- [ ] The generated systemd user unit starts the new service; a real overnight session on Linux completes under it.
- [x] The old supervisor stays in place until cutover (15).

## Comments

- 2026-11-19 (from ticket 02): one attempt is `midgard-farm-service launch [preset] --session-id ID` (`core/launch.py`, `core/preflight.py`, `core/backup.py`). Exit 78 means a preflight or isolation failure (quarantine, no retry); exit 1 means busy or transient.
  - On INT/TERM/HUP/QUIT the attempt writes `farmer_stop`, allows `SHUTDOWN_GRACE_SECONDS` = 45 s (legacy `stop_grace`), then kills the tree. A forced stop never publishes Known-good.
  - The unit's `TimeoutStopSec` (90 s) must stay above that grace.
  - Known-good: generations behind the `backups/known-good/current` pointer.
  - Test gap: the forced-stop test covers manual launches only. Add a supervised one (forced stop must not publish Known-good).
- 2026-11-20: Done in `7a2073a`. The Windows CI failures (`PermissionError` while polling replaced files) were fixed by ticket 05's `Platform.read_shared` (`3adfade`). CI run 44600114868 passed on Linux and Windows.
  - Ported: 19/20 legacy scenarios directly; #7 and #8 are merged into one stronger test.
  - Policy parity is verified: heartbeat, grace, backoff, quarantine threshold, fatal reasons. Exit 78 → quarantine without retry.
  - The service stays up throughout. A corrupt `session.json` is archived into a startup quarantine. A missing profile leaves the service idle until it appears. Refused Starts are recorded.
  - Independent review: APPROVED after three rounds.
  - Operator step (box 4), after the legacy farm has stopped and the official patch is restored (see ticket 15):
    1. Install the unit: `.venv/bin/python -m midgard_farm.service --print-unit > ~/.config/systemd/user/midgard-farm.service`, then `systemctl --user daemon-reload && systemctl --user start midgard-farm.service`.
    2. Submit a Start with `core.commands.submit`.
    3. Follow the night with `journalctl --user -fu midgard-farm.service`.
