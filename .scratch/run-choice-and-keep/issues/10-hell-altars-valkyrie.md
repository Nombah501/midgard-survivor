# 10: Hell strategy: take altars across the map, always kill the Valkyrie after an MVP

**What to build:** Two behaviours for the operator's Hell meta (`hell-rotation`), where the character effectively cannot die.

1. **Altars.** Today the farmer only steers to an altar within 12 units, with at most 8 enemies around it, at ≥70% HP, after loot; at D30 with 37 oath points it practically never takes one. The strategy gets its own altar policy, set by preset keys so cautious presets keep today's behaviour: map-wide search (nearest reachable first within the priority order), no crowd and HP gates, no 3-altar cap, altars ahead of ordinary loot (loot right at the hero's feet still first), priority order unchanged (`freyja, loki, niflheim, thor, yggdrasil, valkyrie, baldur, odin, emperium`). Only altars in the priority list are taken; `hel` (pushes karma to Niflheim/Randgris) is never taken. Taking an altar means standing within 1.8 units for 2 s of channelling (Baldur pauses when hit), so the farmer must hold position until the channel completes. Each altar taken, and each one skipped with its reason, is logged.
2. **Valkyrie.** After every regular MVP the farmer takes the Valhalla karma route and kills Valkyrie Reginleif before continuing endless. Game facts (local research, 0.2.5): the side is per-run state, not a profile setting; `world.karma.path = "light"` set after `world.start_run` makes `can_route()` true after every MVP without touching the saved profile (setting `value` instead would change loot/elite multipliers); the karma portal spawns next to the return portal and the native autopilot never walks to it; the Valkyrie kill is `karma.route_won()` (route cleared, `won_here`, boon count +1, raid `won` with mvp `reginleif`). The farmer's `route_entered` flag is per run today and must become per MVP. A preset key selects this (`karma_route: "valhalla"`); other presets keep today's behaviour. If the route is refused, log why and continue endless rather than stalling.

**Blocked by:** 08.

**Status:** resolved

- [x] With `hell-rotation`, a real windowed/sandbox run takes altars that are far away and in crowds; logs show ALTAR_TAKE/ALTAR_SKIP with reasons; cautious presets unchanged (covered by a fake-game test of the policy keys).
- [x] After each regular MVP the run logs entering the Valhalla route and a Valkyrie kill before ENDLESS_START; Valkyrie Reginleif cards/kills appear in the run journal; the profile's saved karma preference (if any) is unchanged.
- [x] Static checks, mypy (Linux and Win32), both pytest suites; real scenarios `hell-rotation` (through the final boss), `blocked-portal`, `one-run` and `valkyrie-drill`.

Windowed 0.2.5 evidence: 32 altars taken, including five Baldur channels during the portal window. All 14 regular MVPs were followed by a Valkyrie kill before endless continued; the journal records 14 Valkyries and three Reginleif cards. Assassin Cross defeated Morroc at 2400.1 game seconds without dying. The source profile and installation state fingerprints were unchanged.

Spec: [`../spec.md`](../spec.md).

## Comments

- Operator, 2026-11-21: Baldur's channel pauses on any hit taken in the last 4 s, so in the field it practically cannot be taken. Take Baldur only when the MVP portal is open (run time stopped), then enter the portal. Any altar whose channel stops progressing is dropped.
- Operator, 2026-11-21: in manual play the native auto-levelling with his own priorities gives far stronger stats and skills by minute ~27 than the farmer's planner; the farmer disables the native auto-pick (`endless_auto_pick=false`). Suspected main cause of the Valkyrie death.

### Reginleif investigation (0.2.5)

Same-profile D30/37-oath Prontera pilot at 25 game minutes (two headless runs, speed 10, different RNG): the farmer's scorer had level 280, 45,944 max HP, 31 DEX, 13 VIT and 37,538 kills; native `World._auto_pick` had level 285, 142,109 max HP, 143 DEX, 43 VIT and 45,993 kills. EDP went 78→90 and Signum 93→106, although total metered damage was lower in the native run. Native uses per-class `pick_order`, `pick_limits`, `pick_bans` and global `pick_fill`, prioritizing eligible new skills/evolutions with fill on, then rarity and saved order. `Menus.auto_pick` is a separate bot chooser. The source toggle was `true` and the failed sandbox's was `false`; both farmer and native run startup had written `false`.

Native fight data and movement (`GameData.RAIDS.reginleif`, `MvpRaid._start/_resolve/_update_extra/autopilot_goal`, `RaidTrials.goal`):

| Attack | Telegraph, strike and native movement goal |
| --- | --- |
| Lanza del Juicio | One-second aimed cone, distance 7, angle 1.3 rad, weight 1.8; sidestep perpendicular to its facing. |
| Lanzas de Valhalla | Alternating 2.6-unit lanes across the arena, first wave after 1.4 s and second after another 1 s, weight 1.5; center in the nearest safe lane, then switch for the next wave. |
| Columnas de luz | Six 2.4-radius circles, one under the solo hero, after 1.2 s, weight 1.5; run radially away from the first nearby mark. |
| Caída de Valhalla | Six 2.4-radius circles: first mark after 0.30 s, then one every 0.55 s (rounded up to a raid tick). Each mark locks the target's current XZ position, shows the falling meteor at +0.80 s, and strikes once at +1.00 s. No native movement goal. Weight 1.5 (36.5% max HP raw at D30 before other multipliers). |
| Juicio de Valhalla | 3.5 s cast; hits the whole arena except heroes behind a crystal. Goes behind the nearest remaining crystal (four initially; three uses each); raw weight is 80% max HP before raid multiplier. |
| Égida de las Valkyrias | Shield and three stationary Raydric standard-bearers. Kill all within 12 s to break it and gain 7 s vulnerability; otherwise 45% max HP before raid multiplier. No explicit native guard goal. |
| Einherjar | Five Raydric/Bloody Knight adds around the boss; no piercing strike or explicit goal. The 1.4 s holy aura is visual. |
| Sellos de Asgard | Up to three 1.8-radius circles (one solo), occupied at 7 s or claimed by standing continuously for 1 s; 30% max HP before raid multiplier per unclaimed seal. Native steers into the assigned/nearest seal. |
| Vuelo de la Valkyria | Aimed line, 0.6 s tell, then 0.85 s charge at speed 17, hit at boss radius + 1; weight 1.6. Sidesteps the telegraphed line, no separate dash goal. |
| Balanza de Valhalla | Two 2.6-radius light/dark circles; reach the called side in 5.5 s or take 60% max HP before raid multiplier. Native steers to the correct circle. |

Doom was active on both profiles. It turns non-tick piercing MVP hits into immediate downs regardless of HP; revive effects still work. The failed run earned ten Valhalla revives, took no Yggdrasil altar, and had no remaining leaves when it died. The retained logs do not record exactly when or how it spent them. Route and death logs now expose remaining revives and cumulative leaves consumed.

At preset speed 4/game speed 3, the native-movement D30/37-oath drill (after changing the draft) died on each of five Caída waves: 9 hitbox contacts, 5 piercing hits, 5 deaths. The solo hero was retreating toward the arena rim with no field altar to pursue; native steering had no meteor goal. Other isolated mechanics produced no piercing hits except Égida (one hit, one revive); that trial deliberately increases boss HP to sustain the drill, which also increases the standard-bearers' HP.

**Caída timing and counterplay.** The first mark samples the cast's target, not the position at cast start; every later mark samples that same target again (retargeting only if invalid/downed). Once placed, a circle never follows. Collision checks the hero's XZ center at impact, not the motion path nor the sprite; strictly less than 2.4 hits. Nominal impact times from cast start: 1.30, 1.85, 2.40, 2.95, 3.50, 4.05 s; the raid's mark countdown resets after each tick, so rounding is cumulative. The impact uses a pause-aware SceneTree timer, while hero movement and mark scheduling use the same World frame (movement before the raid), capped at 0.10 s in the farmer's fast mode. At speed 4/game_speed 3 the instrumented headless drill saw 27–33 ms of scaled delta on the frame reacting to each mark (about 7–8 ms real time), and 9.5256 units/s movement. Even base Thief speed 4.9 clears 2.4 units in 0.49 simulation seconds on unobstructed ground. At unusually low frame rates the uncapped strike timer can gain on the capped movement clock; blanket slowdown was not needed in the drill.

Cloaking adds movement speed and evasion; it neither hides the hero from Caída nor grants piercing immunity. There is no Backslide in the 0.2.5 Thief trees. Rogue/Stalker Back Stab is an enemy-targeted blink chain, not free movement; the `blinking` state itself is not protection from piercing. Its 0.15 s `skill_guard` can set actual `_invuln` on the 2 s guard cooldown, and real `_invuln` (including revive grace) is checked before Doom, but that window is not a dependable defense. Assassin Cross does not have Back Stab.

The Hell strategy reacts as soon as the wave exists, before its first mark. It maintains uninterrupted movement in one direction around the arena, steering away from the rim and onto an orbit beyond the crystals. This keeps the hero moving away from each locked center instead of changing direction to chase the next mark or pausing to reach a safe point. The drill runs ten six-mark waves from different rim starts with Doom active and no leaves; it also checks zero contacts, even if a separate invulnerability effect prevented damage.

On the official 0.2.5 pack, the final headless `valkyrie-drill` at preset 4/3 passed: all ten six-mark Caída waves (60 strikes) had zero contacts, piercing hits, or deaths.

The windowed run's original verdict rejected `run_mvps=29` because the judge expected 28. Native accounting includes the Morroc finale as the 29th MVP. The corrected judge passed on the unchanged captured run; the route ordering and finale requirements were not relaxed. Evidence is retained in `.sandbox/ticket-10-evidence.pMHZNc`.
