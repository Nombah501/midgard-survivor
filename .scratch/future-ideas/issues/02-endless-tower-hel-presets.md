# 02: Presets for Endless Tower and Hel with the best saved build

**Status:** needs-triage (needs grilling)

**Idea (Operator, 2026-11-22):** presets for Endless Tower and Hel runs. When the farmer goes there, it should be able to use the best saved build (and similar preparation), not only the current one.

**Conflict to resolve first:** ADR 0008 says the farmer never changes character preparation; the Operator prepares, the farmer plays as-is. Using "the best saved build" means switching a loadout. Options to grill:
- the Operator explicitly opts in per preset ("use saved build X for this mode"), and the farmer applies the game's own saved-build load, then restores the previous one after the session;
- or the farmer only *suggests*/refuses to start when the current build isn't the chosen one (no change).
Any change needs a new ADR superseding or narrowing 0008.

**Questions for triage:**
- What does the game call and store as saved builds in 0.2.7 (slots, what they include: class/job, gear, cards, skills)? Native loader exists?
- How do Endless Tower and Hel differ from regular runs in the run choice (ADR 0009): separate modes, floors, entry costs, win condition?
- What does "best" mean: the Operator's pick, or a metric (highest floor/score from history)?
- Glossary terms needed: Endless Tower, Hel, Saved build.
