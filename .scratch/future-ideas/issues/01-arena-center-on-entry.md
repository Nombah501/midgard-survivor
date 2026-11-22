# 01: Walk to the arena centre on MVP/Valkyrie entry

**Status:** needs-triage

**Idea (Operator, 2026-11-22):** when the farmer enters an MVP or Valkyrie (Reginleif) arena, it should go straight to the arena centre, where the boss spawns, instead of wandering or kiting from the entry point.

**Why:** less time to engage, fewer wasted seconds at high game speed, more predictable position for the telegraph-avoidance layer (ticket 12 of run-choice-and-keep).

**Questions for triage:**
- Is the spawn point always the arena centre in 0.2.7 for every location/MVP, or per-raid data (`raid` node / arena bounds)? Read it from the game, don't hard-code.
- Must not fight the dodge layer: telegraphs and Caída avoidance stay higher priority than the walk.
- Does standing at the spawn point hurt on raids with a spawn burst/AoE? Check against the falls-by-mechanic history before shipping.

**Acceptance sketch:** a verify scenario that enters a raid and asserts the player reaches the spawn area within N game seconds without new `PLAYER_FELL` events; real-game evidence on at least two locations.
