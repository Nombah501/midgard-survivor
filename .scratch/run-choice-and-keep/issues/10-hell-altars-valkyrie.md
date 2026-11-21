# 10: Hell strategy: take altars across the map, always kill the Valkyrie after an MVP

**What to build:** Two behaviours for the operator's Hell meta (`hell-rotation`), where the character effectively cannot die.

1. **Altars.** Today the farmer only steers to an altar within 12 units, with at most 8 enemies around it, at ≥70% HP, after loot; at D30 with 37 oath points it practically never takes one. The strategy gets its own altar policy, set by preset keys so cautious presets keep today's behaviour: map-wide search (nearest reachable first within the priority order), no crowd and HP gates, no 3-altar cap, altars ahead of ordinary loot (loot right at the hero's feet still first), priority order unchanged (`freyja, loki, niflheim, thor, yggdrasil, valkyrie, baldur, odin, emperium`). Only altars in the priority list are taken; `hel` (pushes karma to Niflheim/Randgris) is never taken. Taking an altar means standing within 1.8 units for 2 s of channelling (Baldur pauses when hit), so the farmer must hold position until the channel completes. Each altar taken, and each one skipped with its reason, is logged.
2. **Valkyrie.** After every regular MVP the farmer takes the Valhalla karma route and kills Valkyrie Reginleif before continuing endless. Game facts (local research, 0.2.5): the side is per-run state, not a profile setting; `world.karma.path = "light"` set after `world.start_run` makes `can_route()` true after every MVP without touching the saved profile (setting `value` instead would change loot/elite multipliers); the karma portal spawns next to the return portal and the native autopilot never walks to it; the Valkyrie kill is `karma.route_won()` (route cleared, `won_here`, boon count +1, raid `won` with mvp `reginleif`). The farmer's `route_entered` flag is per run today and must become per MVP. A preset key selects this (`karma_route: "valhalla"`); other presets keep today's behaviour. If the route is refused, log why and continue endless rather than stalling.

**Blocked by:** 08.

**Status:** ready-for-agent

- [x] With `hell-rotation`, a real windowed/sandbox run takes altars that are far away and in crowds; logs show ALTAR_TAKE/ALTAR_SKIP with reasons; cautious presets unchanged (covered by a fake-game test of the policy keys).
- [ ] After each regular MVP the run logs entering the Valhalla route and a Valkyrie kill before ENDLESS_START; Valkyrie Reginleif cards/kills appear in the run journal; the profile's saved karma preference (if any) is unchanged.
- [ ] Static checks, mypy (linux, win32 as in `.githooks/pre-push`), pytest suites; real scenarios `hell-rotation` (to the final boss), `blocked-portal`, `one-run`.

Windowed evidence: 20 altars taken from 25.5–29.4 units away, including three with more than eight enemies nearby; seven Hel altars were skipped. The journal records 10 Valkyrie kills and six Reginleif cards. The hero entered the eleventh Valhalla route but died at game time 1631.6 s (`Valkyrie Reginleif`, `Caída de Valhalla`) before the finale. The source profile fingerprint was unchanged.

Spec: [`../spec.md`](../spec.md).
