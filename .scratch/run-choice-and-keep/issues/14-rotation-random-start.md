# 14: Rotation starts at a random location

**What to build:** "All locations in turn" always starts a new AFK session at Prontera Field, and a full cycle of 23 locations takes 4–5 hours, so short sessions keep farming the same first locations. Each new session's rotation starts at a uniformly random unlocked location and then continues in catalog order with wrap-around, exactly as today. Restarts and crash recovery within the same session keep continuing from the saved position (not a new random start); Resume after Pause continues too.

**Blocked by:** 12 (same files).

**Status:** ready-for-agent

- [ ] A new session starts at a random unlocked location (logged), then follows catalog order; covered by a fake-game test over several seeds and the real `location-rotation` scenario adapted to accept any start.
- [ ] A restart within the session continues from the checkpointed position; covered by `location-rotation-resume`.
- [ ] Static checks, mypy (linux, win32), pytest suites pass.
