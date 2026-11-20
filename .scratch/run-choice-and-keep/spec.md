# Run Choice, Untouched Preparation and Wishlist Keep — Spec

Status: ready-for-agent

Source: the grilling session of 2026-11-20; ADR 0008 (the farmer never changes character preparation) and ADR 0009 (the window owns the run choice; a preset owns only strategy). Vocabulary: `GLOSSARY.md` (Location, Difficulty, Oath, Loadout, Character preparation, Run choice, Preset, Wishlist, Keep, Maintenance).

## Problem Statement

The operator prepares each character by hand before a night of AFK: the loadout, the pet, the card album, the stat points, the skill pick order. Between runs the farmer's own optimisers undo that work: it re-equips whatever its internal score prefers, swaps the pet, spends stat points its own way and rerolls the potential of worn items. What the operator prepared is not what runs.

The operator cannot choose where and how hard to play the way the game lets them. Location and difficulty are baked into presets, the window never edits presets, and oaths are not controllable at all; the farmer just inherits whatever oath set the profile last had.

At the end screen every legendary is cashed in for legend coins, because all presets switch keep off. When keep is on, the farmer picks by its own value score. The operator has no say in which legendaries are worth keeping.

## Solution

The farmer treats the character's preparation as read-only. It never changes the loadout, pet, album, distributed stats, rebirth, skill pick order or the potential of worn items, and nothing can make it.

The window gains a run choice like the game's: the operator picks the character, a location (or Automatic), a difficulty (Automatic or a fixed level within the location's range) and, at difficulty 30, a rank for each oath. The window's lists come from a catalog the farmer publishes from the operator's own profile, so they show exactly the locations, ranges, legendaries and oaths this profile has. The window also owns the maintenance switches. A preset becomes only a strategy: objective, speeds, limits and the ceiling Automatic may reach.

The operator keeps a wishlist of legendary items. At the end screen the farmer keeps an offered item only if it is on the wishlist and not already owned; everything else is cashed in or sold as now.

Every choice is fixed when the AFK session starts or resumes, and remembered per machine.

## User Stories

### Character preparation
1. As the operator, I want the farmer never to change my characters' loadout, so that the equipment I prepared is the equipment that runs.
2. As the operator, I want the farmer never to change the active pet, so that the pet I chose stays chosen.
3. As the operator, I want the farmer never to change the card album, so that my card setup stays as I left it.
4. As the operator, I want the farmer never to spend stat points, so that I decide how my character grows.
5. As the operator, I want unspent stat points to stay unspent during AFK, so that I can spend them myself in the morning.
6. As the operator, I want the farmer never to rebirth a character, so that a reset happens only when I choose it.
7. As the operator, I want the farmer never to overwrite the skill pick order, so that my in-run build is the one the farmer plays.
8. As the operator, I want the farmer never to reroll the potential of a worn item, so that rolls I am happy with are not gambled away.
9. As the operator, I want no setting that re-enables any of this, so that an old or wrong preset cannot undo my preparation.
10. As the operator, I want storage cleanup and keep room-making never to remove a worn item, so that my loadout cannot lose pieces.

### Run choice
11. As the operator, I want to pick the character explicitly in the window, so that the farmer plays the character I prepared.
12. As the operator, I want to pick a location from a list that marks locked locations as unavailable, so that I choose like in the game and cannot pick something the game would refuse.
13. As the operator, I want an Automatic location option, so that the farmer can still choose by the preset's objective when I do not care.
14. As the operator, I want to pick a fixed difficulty from the chosen location's range, so that I control how hard the night is.
15. As the operator, I want an Automatic difficulty option, so that the farmer can adapt the difficulty by income up to the preset's ceiling.
16. As the operator, I want the difficulty range to follow the location I picked and my profile's progress, so that the window never offers a level the game would not allow.
17. As the operator, I want an oath panel with a rank choice (off, 1, 2, 3 where the oath has that rank) for every oath, so that I set handicaps like in the game.
18. As the operator, I want the oath panel active only at difficulty 30, so that I do not pick oaths the game would ignore.
19. As the operator, I want the oaths I pick in the window to apply to the farmer's runs without changing the oath set saved in my profile, so that my own play keeps my own oaths.
20. As the operator, I want no oaths applied when difficulty is Automatic, so that the adaptive mode never stacks handicaps I did not see.
21. As the operator, I want the window to show the oath points total of my selection, so that I know the reward bonus I am buying.
22. As the operator, I want location, difficulty and oath names in the game's language, so that they match what I see in the game.
23. As the operator, I want my run choice remembered on this machine, so that a nightly start stays one click.
24. As the operator, I want the run choice fixed when I press Start or Resume, so that every run of a session belongs to one known choice.
25. As the operator, I want to change the run choice while paused or after Finish, so that I can redirect the farm without restarting the app.
26. As the operator, I want the AFK screen and history to show the location, difficulty and oath points of each run, so that I can compare what each choice earned.

### Catalog
27. As the operator, I want the window's lists built from my own profile, so that unlocked locations and ranges are exactly mine.
28. As the operator, I want the catalog refreshed every time the farmer starts the game, including the smoke check after a game update, so that new unlocks and new game content appear without manual steps.
29. As the operator, I want only Automatic offered and the wishlist disabled until a catalog exists, so that I can still start a session on a fresh install.
30. As the operator, I want the window to say when the catalog was last refreshed, so that I know whether the lists may be stale.
31. As the operator, I want the farmer to check my run choice against the live game when a session starts, so that a stale catalog cannot send it somewhere invalid.
32. As the operator, I want an invalid run choice (locked location, difficulty out of range, unknown oath or rank) to end the session with a clear reason in the window, so that the farmer never silently plays something I did not choose.

### Wishlist keep
33. As the operator, I want to search all legendary items of the game by name in the window, so that I can find the ones I want.
34. As the operator, I want to add and remove legendaries from my wishlist, so that I decide what the farmer keeps.
35. As the operator, I want the farmer to keep an offered legendary only when it is on my wishlist, so that storage does not fill with things I do not want.
36. As the operator, I want the farmer not to keep a wishlist item I already own, so that I do not collect duplicates.
37. As the operator, I want the farmer to keep a wishlist item again after I delete my copy, so that "owned" always means owned right now.
38. As the operator, I want the farmer to pay for keep after a defeat only within the preset's zeny limit, so that a wishlist item never drains my zeny.
39. As the operator, I want the farmer to make room in a full storage only by removing the weakest unworn, non-legendary item without potential or trait, so that nothing valuable is lost to make room.
40. As the operator, I want a skipped wishlist item (no room, no zeny) recorded in the log and the run journal, so that I can see what I missed.
41. As the operator, I want everything not kept cashed in for legend coins or sold as today, so that unwanted drops still turn into currency.
42. As the operator, I want the run journal to list what was kept, so that I can see the night's wishlist hits.
43. As the operator, I want my wishlist remembered on this machine, so that I set it once.

### Strategy presets and maintenance switches
44. As the operator, I want presets to describe only a strategy (objective, speeds, limits, Automatic ceiling), so that the run choice lives in one place.
45. As the operator, I want presets that only fixed a location, difficulty or character removed, so that the preset list holds real strategies.
46. As the operator, I want switches in the window for Kafra/Sage upgrades, fusion of spare card copies, Star Smith on unworn stored items, and storage cleanup, so that I control what the farmer spends between runs.
47. As the operator, I want Star Smith never to touch a worn item even when switched on, so that the switch cannot affect my preparation.
48. As the operator, I want my switch settings remembered on this machine and fixed at Start or Resume, so that the night behaves as I set it.

## Implementation Decisions

### Contract between window, service and farmer
- The Start command carries, besides the preset path and character, the run choice (location id or Automatic, difficulty level or Automatic, oath ranks), the wishlist (item ids) and the four maintenance switches. The service validates the payload's shape like it validates the character today and rejects malformed requests through the existing rejection path.
- Resume carries the same fields, so a choice changed while paused applies from the next run. Pause and Finish keep ADR 0004 semantics.
- The service builds `farmer.cfg` from the preset's strategy fields plus the request's fields; the preset never supplies location, difficulty, class or oaths (ADR 0009). The existing character selection path is extended, not duplicated.
- The farmer reads location, difficulty, oaths, wishlist and switches only from `farmer.cfg`. Automatic location keeps today's selection by objective; Automatic difficulty keeps today's adaptive selection under the preset's ceiling.
- The window persists the last run choice, wishlist and switches in its per-machine state next to the remembered character and preset.

### Catalog
- At game start, before the first run, the farmer writes a catalog file into the profile. It is written atomically like the status file. It holds: unlocked locations with display names and the current difficulty range per location; the maximum difficulty; all oaths with display names, ranks, rank descriptions and point costs; all legendary items with ids and display names; and the ids of items currently owned, for the wishlist view. Display names come from the game's translation of its own data.
- The smoke run after a farmer patch rebuild runs on a copy of the operator's profile; the app publishes the catalog it produced as the latest catalog, so a fresh install has one before the first AFK session.
- The window reads the latest catalog and shows its refresh time. Without a catalog, only Automatic choices are offered and the wishlist editor is disabled.
- At session start the farmer validates the run choice against the live game: an unknown or locked location, a difficulty outside the location's range, an oath that does not exist or a rank it does not have, or oaths with a difficulty other than 30, ends the session as a failure with a reason naming the field. The supervisor treats it like other preflight-class failures that retrying cannot fix.

### Farmer behaviour
- Maintenance no longer contains loadout, pet, album, stat, rebirth or pick-order writes; that code and its config keys are removed, not disabled. Remaining maintenance: achievements, Kafra and Sage upgrades, fusion of spare card copies, Star Smith restricted to stored items not worn by any character, storage cleanup. Each of the four switchable actions follows its switch.
- Profile pick order and job path: the farmer reads the profile's pick order and never writes it. The job path still comes from the chosen character because the game's job change reads it per run.
- Oaths are handed to the game per run through the game's one-run oath override; the profile's own oath set is never written. Oaths are only passed when the difficulty is 30.
- Keep: the value-based keep and its switch are removed. An offered item is kept if and only if it is on the wishlist, is not owned (no stored item with the same id), passes the game's keep rules (not permanent, not lent, unique not already held), and either the keep is free (victory or Ymir) or the paid cost fits the zeny limit. Full storage uses the existing room-making rule. Skips are logged with a reason and recorded in the run journal. Everything not kept is settled as today.
- Status and run journal record, per run, the location, difficulty, oath points and kept items, so the window can display them.

### Presets
- `stage`, `danger`, `class`, `class_rotate`, `auto_keep`, `auto_loadout`, `auto_pet`, `auto_cards`, `auto_stats`, `auto_rebirth`, `auto_rebirth_lv`, `override_pick_order` and `pet_priority` leave every preset and the farmer's config validation. The switchable actions' keys (`auto_upgrades`, `auto_sage`, `auto_fuse`, `auto_potential`, `auto_storage_prune`) also leave the presets, because the window supplies them. A preset still containing any of these keys is rejected by preflight as unfixable, naming the key, so an old preset fails loudly instead of silently being ignored.
- `synx-hell` and `sniper-hell` are deleted. `one-run` stops being a selectable preset and becomes the smoke and verify configuration, which now names its own location and difficulty explicitly. The remaining presets (`crumbs`, `night`, `steady`, `zeny`, `progress`) keep only strategy.
- The window's preset description shows the strategy (objective, ceiling, limits) instead of location and difficulty.

### Window
- The AFK screen gains: location picker, difficulty picker, oath panel with points total, wishlist editor with search, four maintenance switches, catalog refresh time. All are editable only when Start or Resume is possible, under the same gating as today's character and preset pickers.
- The current-run and history views show location, difficulty and oath points.

## Testing Decisions

- Good tests assert what the operator or the game can observe: the `farmer.cfg` the service writes, the remembered choices, what the window shows and enables, and the state of the profile after real runs. They do not assert internal functions, log wording or field order.
- **App seam: Start/Resume request → `farmer.cfg` and remembered state.** Extend the GUI model tests (prior art: the test that Start writes only a request and remembers both picks; the fixed-preset character test) and the service launch tests (prior art: manual launch uses the preset; bad preset does not overwrite config). Cover: the run choice and wishlist land in `farmer.cfg`; the preset never contributes location, difficulty or class; a preset with a removed key is rejected as unfixable; malformed requests are rejected; without a catalog only Automatic is enabled; locked locations are not selectable; the oath panel is enabled only at difficulty 30; the difficulty list follows the location's range from the catalog. Catalogs in these tests are fixture files.
- **Farmer seam: `farmer.cfg` → profile after real runs**, through the existing `midgard_farm.verify` scenarios on a sandbox copy of the profile (prior art: the bounded scenarios built from the one-run config plus a scenario override and a judge). New or extended scenarios:
  - Preparation unchanged: loadout, pet, album, stats, rebirth state, pick order and potentials of worn items are identical before and after a run with all switches on and unspent stat points present.
  - Run choice honoured: a fixed location, difficulty and oath selection appear as the run's target and oath points in status and journal; the profile's own oath set is unchanged.
  - Wishlist keep: with a wishlist containing an offered item, only that item is added to storage; an owned wishlist item is not kept again; non-wishlist legendaries are cashed in.
  - Invalid choice: a locked location ends the session as a failure with a reason naming the location.
  - Catalog: a game start writes a catalog that lists the profile's unlocked locations, oaths and legendaries.
- The smoke run's catalog publication is covered in the existing smoke/game-update tests with the fake game, which writes a fixture catalog.
- No GDScript unit tests are introduced.

## Out of Scope

- Any automatic optimisation of loadout, pet, cards, stats, rebirth or pick order, including opt-in switches (ADR 0008).
- Writing the profile's own oath set.
- Wishlist conditions beyond the item itself (potential, trait, refine), and keeping non-legendary items by rule.
- Editing or creating presets from the window; per-run rotation of location, difficulty or character within a session.
- Endless Tower, Hel Tower and Emperium Festival runs, which the farmer does not automate.
- Changing the run choice in the middle of a running session without Pause or Finish.
- Syncing choices or wishlists between the two machines.

## Further Notes

- This reverses the app spec's decision that the preset carries location and difficulty and the window never edits presets (`../midgard-farm-app/spec.md`, AFK session screen); ADR 0009 records why.
- The oath facts (oaths apply only at difficulty 30, the per-run override, the oath list, point costs and the star crumb bonus) come from the decompiled snapshot under `analysis/`. The snapshot may predate the current official patch; the first ticket that touches oaths verifies them against the current patch before building on them.
- Before changing the farmer, supervisor or verify, read `docs/agents/farmer-map.md`. After any farmer change, rebuild the farmer patch before running verify scenarios. The real profile and real install belong to the operator.
