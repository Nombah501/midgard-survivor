# 15: Record AFK runs in local progression like manual runs

**What to build:** The game's autopilot flag makes native settlement skip local progression that a manual run records (evidence: local://progress-loss.md from the 2026-11-21 investigation): **Album → History** entries, Hell title and oath progress, and altar achievement counters. Rewards themselves are banked. The operator wants farmer runs to count in these local records exactly like his manual runs.

Rules:
- Only local progression the game records for a manual run of the same outcome; never anything a manual run would not get, never character preparation (ADR 0008).
- Never submit farmer runs online: leaderboards, cloud, Epic/EOS. The game already marks autopilot records `online: false`; that must hold.
- Prefer the game's own recording code paths (e.g. run them for the farmer's settlement with the autopilot gate lifted only for those calls) over re-implementing the bookkeeping; whichever is chosen, it must be idempotent across crash recovery (Run ID, ADR 0001).

**Blocked by:** 12, 13, 14 (same files).

**Status:** ready-for-agent

- [ ] Inventory in 0.2.7 of every local record skipped under autopilot, with file:line, recorded in this ticket.
- [ ] A real sandbox run (D30/37, a win) adds an Album → History entry, advances Hell title/oath progress and altar counters by exactly what a manual run of that outcome adds; a crash-after-settlement scenario does not record it twice.
- [ ] No online submission: verified by code path and by the sandbox running offline with no network calls attempted for these records.
- [ ] Static checks, mypy (linux, win32), pytest suites pass.
