# 11: Navigation on complex maps: no corners, no wall-hugging, reach far altars in time

**What to build:** The operator watched the bot on complex (indoor/maze) locations in the Hell meta and reports three faults:

1. **Corners.** During free combat the hero drifts into corners and dead ends and takes much more damage there than in the open field. Free-roam steering must prefer open, well-connected ground (keep escape directions, avoid dead ends and narrow pockets) instead of drifting along walls.
2. **Walls.** When heading to a goal (an altar, loot, a quest goal), the hero walks straight into a wall/texture and keeps pushing against it; on complex maps he cannot find his way out by himself. Every non-raid goal must be reached by a path over walkable tiles (the farmer already builds an `AStarGrid2D` for blocked raid portals since ticket 08), with stuck detection and re-planning, never by pushing straight into geometry.
3. **Far altars.** Altars that exist on the map are not picked up when far away, and by the time the hero walks over they have vanished. Altar choice must use path length (not straight-line distance) against the altar's remaining lifetime, consider every altar on the map (check whether the game exposes all of them or only nearby ones), and skip ones that cannot be reached before they expire (logged `ALTAR_SKIP reason=expires_first`).

**Blocked by:** 10.

**Status:** resolved

- [x] Measured baseline first, on the real game in sandboxes, across the most complex unlocked locations (pick by map structure; include at least Glast Heim, Clock Tower, Niflheim, Toy Factory, Thanatos Tower, Bio Laboratory, Juperos): time spent with no progress toward the current goal, time near walls/in dead ends, damage taken per minute, altars taken vs expired-before-arrival. Same metrics after the fix, reported side by side.
- [x] No goal ever leaves the hero pushing into geometry for more than a short re-plan window; a deterministic check (verify scenario or fake test) covers a goal behind a wall and a maze.
- [x] Far altars reachable in time are taken; unreachable-in-time ones are skipped with a reason; covered by a check.
- [x] Raid fights, Valkyrie Caída avoidance (ticket 10), portals and the `valkyrie-drill`, `blocked-portal`, `one-run`, `hell-rotation` scenarios still pass.
- [x] Static checks, mypy (linux, win32 as in `.githooks/pre-push`), pytest suites pass.

Spec: [`../spec.md`](../spec.md).

`field-navigation` on 0.2.5: the pre-fix sandbox let the Freyja bait expire and timed out pursuing maze loot. The fixed sandbox logged `expires_first` at 0.2 game seconds, channelled Loki from 16 units away, collected the card, and escaped the same cul-de-sac with no goal. The fixture uses native map collision, altar lifetime/channel, and pickup collection.

Navigation patch, headless 0.2.5 (180 game seconds per location, Assassin Cross, D30/37 oaths, Hell strategy). **Before → after**; no scripted spawns. Near-wall samples have a blocked tile in the surrounding 3×3; pockets have at most two cardinal exits or at least four blocked neighbours. Stalled samples moved less than 0.25 world units between 0.25-second samples with essentially the same goal. Damage is the native taken meter per game minute.

| Location | Stalled s | Near wall s | Pocket s | Damage/min | Altars taken/expired |
|---|---:|---:|---:|---:|---:|
| Glast Heim | 7.53 → 0.27 | 30.29 → 20.33 | 17.01 → 0.56 | 27,043 → 43,029 | 2/0 → 2/0 |
| Clock Tower | 9.62 → 0.51 | 51.66 → 15.70 | 28.28 → 0.00 | 56,046 → 16,571 | 2/0 → 2/0 |
| Niflheim | 1.33 → 0.00 | 48.00 → 33.99 | 4.27 → 0.53 | 22,216 → 9,598 | 2/0 → 2/0 |
| Toy Factory | 5.94 → 0.00 | 109.68 → 74.21 | 10.29 → 2.63 | 44,269 → 51,419 | 1/0 → 2/0 |
| Thanatos Tower | 5.62 → 0.27 | 33.44 → 14.18 | 0.00 → 2.16 | 50,315 → 45,849 | 1/0 → 2/0 |
| Bio Laboratory | 2.41 → 0.00 | 56.94 → 64.97 | 1.04 → 1.88 | 47,813 → 29,334 | 2/0 → 2/0 |
| Juperos | 45.88 → 0.00 | 111.36 → 29.55 | 94.87 → 0.27 | 80,323 → 31,247 | 0/0 → 2/0 |

The first full headless navigation run died to Baphomet's field `Embestida` at 319.9 s (two leaves spent), before the MVP arena. This field hit is not the arena mechanic: `BossBrain.tick` calls `take_damage` without piercing. The separate Hell Shadow version deals environmental hazard damage without an MVP source. Neither triggers Doom's instant-down rule. The native field brain locks the heading at the 0.8 s tell, then slides at 17 units/s for 0.85 s and can contact the hero once per dash (within `enemy.radius + 1`). Field steering reads those states and steps off the corridor; raid movement is unchanged.

In three additional six-minute Prontera runs each, HEAD and the navigation-only candidate both had zero deaths, leaves spent, and Baphomet damage-meter hits. The original death did not reproduce; this sample cannot attribute it to either navigation or chance.

A fourth, instrumented pair confirmed native drafting (163 HEAD / 161 navigation `AUTOPICK` choices). At 319.02 s, HEAD was level 158 with 23,627/23,627 HP and STR/AGI/VIT/DEX 43/40/28/50; navigation was level 149 with 20,608/20,608 HP and 35/52/22/50. The navigation run spent one leaf on `Embestida` at 231.20 s (level 119), then finished the six-minute sample. Across all four samples per build: 0 versus 1 leaf spent, no deaths on either build. The sample is too small to attribute the original death to steering or draft RNG.

The real `field-charge-drill` recorded four contacts in four forced native charges before avoidance, and zero contacts, falls, or deaths in all four after it.

The full headless `hell-rotation` passed on the charge-avoidance candidate: Morroc defeated at 2,400.05 game seconds, 16 Valkyrie kills, 34 altars taken, 91,321 kills, and no death.

Repeat three-minute samples (HEAD → navigation-only; same config, independent RNG):

| Location | Stalled s | Near wall s | Pocket s | Damage/min | Altars taken/expired |
|---|---:|---:|---:|---:|---:|
| Glast Heim | 4.24 → 0.29 | 40.61 → 16.26 | 14.40 → 0.25 | 33,427 → 13,311 | 1/0 → 2/0 |
| Niflheim | 0.26 → 0.27 | 30.68 → 50.57 | 1.10 → 1.87 | 12,657 → 13,722 | 2/0 → 2/0 |

In the two recorded pairs, Glast Heim wall exposure and pocket time improved, but the sign of the damage change flipped. Niflheim wall exposure, pocket time and damage all changed in opposite directions across pairs. These samples do not establish a consistent damage regression.

## Comments

- Coordinator, 2026-11-21: repeat 3-minute samples (old navigation → final) to separate noise from regressions: Glast Heim near-wall 40.6 → 16.3 s, pocket 14.4 → 0.25 s, damage/min 33.4k → 13.3k; Niflheim near-wall 30.7 → 50.6 s, damage/min 12.7k → 13.7k (the first sample's 22k → 43k damage was noise; Niflheim near-wall time stays a minor open observation). Field-charge drill: old 4/4 contacts, new 0/4. Full hell-rotation on the final candidate: Morroc at t=2400, 16 Valkyries, 34 altars, no deaths.
