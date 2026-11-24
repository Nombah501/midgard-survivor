# 09: Endless Tower and Torre de Hel as run choices

**Status:** resolved (shipped in 0.4.0: Endless Tower and Torre de Hel as run choices; see CHANGELOG)

## Operator decisions (2026-11-22)

- Both towers: normal Endless Tower and Torre de Hel (Hel only when the game reports it unlocked).
- Goal: climb until the hero dies (or the Operator presses Finish). No target floor.
- Start floor: the Operator chooses it in the window from the checkpoints the game offers (normal Tower; Hel always starts at floor 1).
- Snapshot: the farmer picks the most-levelled eligible Tower snapshot automatically — highest level, then XP progress toward the next level, then newest. Locked snapshots are never spent automatically.
- One snapshot spent per Start: after the tower run ends, the session ends. [Default chosen by the agent; the Operator described ranking, not repetition. Revisit if he asks for chained runs.]

## Game facts (0.2.7, `/home/n501/ms-research/GameModesResearch/report.md`)

- Entry spends a snapshot (`Save.data.tower.builds`) via `take_tower_build`, which flushes before run creation. Native `World.start_tower(index, floor, hel)`.
- Snapshots are saved at the end screen only for non-autopilot runs (`menus.gd:15104–15119`): farmer runs never produce them today. Parity fix: at settlement, once per run, call `Save.add_tower_build(RunSave.hero_snapshot(world))` when the native eligibility holds (level ≥ 20, Tower open or ready, not training, not in a Tower). Autopilot stays unchanged; nothing online.
- Eviction: the native list keeps 10 recent unlocked (+ up to 10 locked); farmer saves would evict the Operator's manual snapshots. Keep at most one farmer-created snapshot: replace it only with a better one, never evict manual entries.
- The named Loadout loader (`_kit_apply`) rewrites preparation: never call it (ADR 0008).
- Floor 100 is a milestone, not a win; the run ends on final death or Finish. Keep autopilot through native settlement so no leaderboard submission happens.

## Acceptance

- Window: Location list gains "Endless Tower" and "Torre de Hel" (Hel disabled with the reason when locked); a start-floor picker for normal Tower; the chosen snapshot (class/job, level, date) shown before Start with "this snapshot will be spent".
- Farmer: tower lifecycle (camp/stairs/blessings native), MVP arenas exit through the return portal, Naght rewards collected; journal records highest floor and end cause, not MVP wins.
- Exactly one snapshot consumed per Start, preparation unchanged, no online submissions — proven in a real sandbox scenario; restart after a crash never spends a second snapshot (fail closed).
- Farmer settlement saves at most one farmer snapshot and never evicts manual ones (sandbox scenario).
