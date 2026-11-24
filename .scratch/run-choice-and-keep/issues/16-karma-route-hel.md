# 16: Hel route as a karma choice, or a random light/dark rotation

**What to build:** `karma_route` accepts only `natural` and `valhalla`; `valhalla` forces `world.karma.path = "light"` after `start_run`, so AFK sessions never take the Niflheim route (Fallen Randgris, Pact of Hel). Add a `hel` choice and a `rotate` choice that picks light or dark at random per run (logged at run start, kept across restarts of the same run).

Game facts (0.2.10, `game_data.gd` KARMA_ROUTES / VALHALLA_* / HEL_PACT_*; `karma.gd` `on_kill`, `_tick_boon`; `player.gd` damage-taken path):
- Valhalla per win: +1 revive, +20% max HP, +20% risk damage, +15% XP, regen 2% max HP/s per boon. Route foes +35% HP, +10% damage, no knockback.
- Hel pact per win: +50% risk damage, +20% damage taken per boon (linear), kill heals 2% max HP per boon. Route foes +15% HP, +35% damage, +15% speed and a 6% max HP death burst (radius 2, 0.6 s tell).
- Each opened corrupt chest adds a Hel mark: hero damage ×1.08, enemy damage ×1.06. Under autopilot every corrupt chest is a 50/50 open/purify roll.
- The side comes from the karma sign unless `path` is set: dark needs `path = "dark"` (or negative karma). The farmer today rejects every Hel altar (`_altar_rejection`), so a dark route must decide whether Hel altars (−15% max HP, ×1.10 damage) join the altar priority.

Observed on the owner's Champion (Hell 15, Oath 40, 40 min, same gear): dark runs gave +15–18% zeny and +5% kills over light, but ended with 3–6 revives and 1.14–1.20M max HP instead of 16 revives and 3.67M. Total damage taken was similar (29–49M dark, 38M light). Hel suits supervised play; light stays the safer AFK default.

**Operator decisions (2026-11-25):** the window offers Route = Valhalla / Hel / Random each run (no "natural"); on the dark side the farmer takes Hel altars. Presets are replaced by a fixed Mode (ADR 0011). Ticket 14 ships in the same change.

**Status:** ready-for-agent

- [x] `karma_route` accepts `natural`, `valhalla`, `hel`, `rotate`; the window offers Valhalla / Hel / Random each run (ADR 0011).
- [x] `hel` sets `path = "dark"`, enters the Niflheim portal after each regular MVP and waits for `RANDGRIS_KILLED` before continuing endless; arena timings record `kind=randgris`.
- [x] `rotate` picks a side per run (`KARMA_SIDE … route=rotate`), checkpointed in `pre_run`. A crashed run is lost per ADR 0001 and the next run rolls again.
- [x] Hel altar policy: take on the dark side, reject otherwise (Operator, 2026-11-25). Corrupt chest open/purify split: not logged (out of scope).
- [ ] Real drill: one Niflheim clear passed (`hel-route-drill`, 0 falls, `boon=hel_pact`, 2026-11-25). Not yet covered: repeated Endless cycles, Hel altar pickup in a real run, Fallen Randgris mechanics inventory like ticket 12.
- [x] mypy (linux, win32) clean; `pytest` 750 passed/26 skipped + test_verify 144 passed + farmer/tests 87 passed (2026-11-25).
