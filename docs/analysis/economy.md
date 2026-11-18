# Midgard Survivors 0.2.3 — farming economy

Evidence: effective 0.2.3 GDScript in `analysis/src/`. Citations below use `file.gd:line`. Code excerpts establish what the game rolls; `[INFERENCE]` denotes derived expectations, assumptions or recommendations, not measured play. Rates are per **game-clock** minute unless stated otherwise. A drop, its pickup, its conversion to profile resources and its appearance on the results screen are four different events.

## 1. Profile resource ledger

| Resource | Earned / banked | Used for |
|---|---|---|
| Zeny | Ground `LOOT`, small-box cash, sold equipment and card-bag cards, Golden Poring, steal effects and the daily `+50%`. Most zeny is credited at source, not at the end; Festival daily uses a separate direct credit (`main.gd:378–393,13102–13114,14201–14216,14239–14247,15705–15725`; `menus.gd:1504–1529`). | Account upgrades, class unlocks and Sage training, paid keep, town crafting, cooking and cosmetics; run purchases debit both run and profile zeny (§10). |
| Poring Coin (`Save.coins`) | Eligible kill `0.004% × drop / C`, max 3 successes/run from this channel; raid MVP `3% × drop`, uncapped by the mob limit; Festival `1%` per daily check; Hel Tower first clears F20/F70 give 3/5; achievement claims add the achievement's `coins`; gacha duplicate returns 1. `main.gd:344–353,1348–1357,11500–11507`; `mvp_raid.gd:1355–1360`; `save.gd:482–496,510–528,1136–1148`; `game_data.gd:173–176,5855–5860`; `menus.gd:1517–1525`; `gacha_panel.gd:496–506`. | Cosmetic gacha: `GACHA.coins * n` = 5/spin (alternative 20,000,000 zeny/spin), not a combat-stat purchase (`game_data.gd:1387–1388`; `gacha_panel.gd:315–323,485–506`). |
| `oridecon`, `elunium` | An ore pickup is a uniform ID from the two-entry `ORES` table. Regular kill, elite/mini-boss packages, Festival and transmutation (§4). | Run refine: one matching ore from temporary inventory. Town refine, grading and transmutation: profile materials. Oridecon is for weapons, Elunium for non-weapons (`equipment.gd:387–388,1425–1447`; `game_data.gd:5632–5638,5782–5788`; `menus.gd:25433–25448`). |
| `enriched_oridecon`, `enriched_elunium` | Elite-independent non-MVP boss roll, real MVP raid clear package, Festival, transmutation (§4). | Town refine; legendary sockets cost 1 then 2 matching enriched ores; conversion up/down (`equipment.gd:361–376`; `menus.gd:25293–25305,25404–25410`; `game_data.gd:5818–5829`). |
| `hd_oridecon`, `hd_elunium` | Real raid MVP roll, Festival, conversion from enriched (§4). | Town refine, grade A/S and conversion down (`menus.gd:23789–23801,25404–25410`; `game_data.gd:5752–5756,5782–5788,5827–5828`). |
| `star_crumb` | Eligible kill by mode, Festival, Hel Tower once-only milestones (§3). | Star Smith: `1 + POTENTIAL_LOCK_COST * locked` = `1 + 3*locked` crumbs per roll; keeps selected lines (`potential.gd:115–145`; `game_data.gd:5660–5673`; `star_smith_panel.gd:738–754`). |
| `hel_tear` | Hel Tower account milestones: 1 at F40, 3 at F100, conditional 2 at F50 (§3). | One tear deterministically turns a semi-perfect Legendary potential line into a perfect one; `line["p"] = true` (`potential.gd:160–172`; `star_smith_panel.gd:774–783`). |
| `hel_requiem` / wings | One bound Requiem on the eligible class's first Hel Tower Lord clear; independently, eligible classes get a Sword Wings unique on Tower Lord clear. Eligibility is per class; ordinary wings also check current gear/bag. The clear schedules awards at 1.6/3.6 s; save-load recovery covers owed Hel rewards (`main.gd:11533–11542,11613–11678`; `save.gd:248–255,1093–1103`; `game_data.gd:5645,7026`). | Consume one Requiem via `Save.awaken_wings(uid)` on stored, unawakened Sword Wings, sets `it["hel"] = true`. Wing upgrade feathers are **not** Requiems or Hel Tears: `maxi(0, sum(rebirth_lv(cid)) - wing_feathers_spent)`; +1 refine per feather (`save.gd:816–835,1108–1116`). |
| `legend_coin` | Explicit sale/auto-sale of gear: Legendary +1, Unique +3 (`game_data.gd:5653`; `equipment.gd:949–962`). Not Poring Coin and not granted by the final non-lent Legendary/Unique bag sweep (§8). | No spend path found in effective scripts; wallet explicitly says they will have a use later (`menus.gd:23321–23325`; `equipment.gd:949–962`; `save.gd:2264–2274`). |
| Cards | Collected eligible enemy drops, separate MVP fight-add roll, quest rewards, rebirth card; regular copies saved upon pickup; run card-bag sale does not debit saved copies (§6). | Select Album cards for future runs, in-run socket or cash out extra run copies, fuse saved copies into an Eternal card for persistent gear (§6). |
| Pets | Unowned, eligible tame-item drop followed by a tame roll; or deterministic quest rewards (§7). | Permanent unlock, equipped from Album; not consumed/sold by pet skills (`main.gd:13477–13517`; `save.gd:1291–1308,1378–1382`). |
| Unique gear | Stage or route-specific rolls, Tower wings, explicit reward paths; `_found_unique` immediately stores even over cap, also hands gear to the run (§5/8). | Equip/keep/use or sell for 3 legend coins; socket and refine fees use unique-specific multipliers (`main.gd:11573–11609`; `equipment.gd:322–338,949–962`; `game_data.gd:7080–7086`). |
| Ymir fragments (`Save.ymir`) | `Save.add_ymir_fragment(1)` on **actual raid fight** MVP victory; no danger RNG and not just any enemy with the `mvp` flag. Co-op clients credit host-reported MVP count in settlement (`mvp_raid.gd:1337–1353`; `main.gd:3002–3011`; `save.gd:1609–1616`). | `data["ymir"] = ymir_fragments() - REBIRTH_FRAGMENTS` = 4 per eligible first class rebirth at class level 30; resets class XP/level/stat allocation and grants `randgris_card` (`save.gd:1594–1631`; `game_data.gd:1008,4685–4689`). |

Trading is redistribution, not farm yield: material offers exclude `bound` IDs; the receiver credits the offered material count, card copies and zeny. `trade.gd:221–228,465–479,511–519`. Gacha refund probability is `[INFERENCE] Σ_r P(r) * owned_eligible_r / eligible_r` when every rarity pool is nonempty and pity is inactive, using weights `[.69,.22,.075,.01,.005]` for common through unique. The pool filters for gacha availability/art and falls back to all eligible art if empty; at 11 non-Legendary results `roll("legendary")` replaces the rarity roll; a Legendary resets pity. Refund is exactly one Coin on a duplicate (`game_data.gd:1387–1388`; `gacha_panel.gd:449–503`).

## 2. Per-kill reward pipeline

`spawn_enemy` chooses the definition, scales HP/damage/XP, can fuse several crowded spawns into one enemy, and flags specials. `Enemy.setup` assigns `def = GameData.MONSTERS[id]`, `max_hp = def.hp * hp_scale` and `xp = def.xp`; `Enemy.die()` does visuals/state, not drops. `damage_enemy` stores `e.last_hit_by = src`, then calls `_kill(e)` at `e.hp <= 0.0`. `_kill` handles dummies, training, props, Festival targets and MVP shadows before the ordinary pipeline, then increments `kills` and chooses the last hitter (fallback local player). A RISE repeat (`rose`) suppresses normal loot/card/box/coin/special branches, but is not an explicit test on the crumb roll. `main.gd:5402–5506,6001–6022,11298–11344,11367–11386,11407–11408,11437–11507`; `enemy.gd:224–242,310–320,892–912`.

Zeny is **not** a competing alternative to card or equipment. The independent `LOOT` roll (monster table `game_data.gd:5355–5536`) creates all `count` piles or none; the item/sprite labels in the data are not persistent drops. Example base payout per kill before multipliers: Poring `0.22 * 6 = 1.32`, Willow `0.30 * 15 = 4.5`; Angeling `6*60 = 360`, Baphomet `15*120 = 1,800`. Ground-value and pickup formulas:

```gdscript
if loot.is_empty() or randf() > float(loot.chance): return
var thin = 1.0 if e.is_boss or e.def.get("elite", false) else GameData.crowd_zeny_mult(kills)
var value = maxi(1, roundi(int(loot.zeny) * (float(GameData.FEROCIOUS.zeny) if e.feroz else 1.0) * thin))
var z = roundi(p.value * player.loot_mult / GameData.coop_spawn(heroes.size()))
```

`main.gd:13102–13114,14239–14247`; `FEROCIOUS.zeny = 3.0` (`game_data.gd:8644–8646`). Veloz/Maldito/Gigante/others assigned with `make_special` also set `feroz = true` (`enemy.gd:310–318`). The roll is unaffected by `drop_find` or danger. Both rounding steps are per pickup/pile as represented at collection, not one `roundi` on the run total.

```gdscript
hard_loot = danger_reward(danger) * (1.0 + FEATURED_BONUS if featured else 1.0) \
    * (1.0 + FRENZY_ZENY if frenzy and tower_start == 0 else 1.0) * oath_zeny()
loot_mult = (1.0 + mods.get("loot", 0.0) + curse * GameData.CURSE_ZENY) * hard_loot
card_mult = 1.0 + mods.get("card", 0.0) + GameData.CARD_LUK_BONUS * eff_stat("luk")
oath_zeny = 1.0 + GameData.OATH_ZENY * oath_points()
oath_mats = 1.0 + GameData.OATH_MATS * oath_points()
```

`main.gd:250–255,1378–1394,1420–1423`; `player.gd:1591–1592`; `game_data.gd:5733–5734,8947,10019–10026,10101–10108,10364–10368,11378–11382`. Values: featured +25% (date-selected stage), Frenzy +30% (only with `tower_start == 0`), Oath +2% zeny and +3% materials per point, `CURSE_ZENY = 2.0`, LUK +0.02 to `card_mult` per effective point. `hard = danger >= 8` is a separate flag, not a second ×1.5 reward multiplier on this path. Define `drop = 1.0 + float(killer.effects.get("drop_find", 0.0))`, `mats = drop * oath_mats()`, `C = 1.0 + 0.6 * maxi(0, heroes.size() - 1)` (`main.gd:11384–11386`; `game_data.gd:9049,9061–9062`). Drop-find sources include lucky gear traits and potential (`game_data.gd:5702,7616`).

**Order and competition** (`main.gd:11376–11507`): normal cash roll; guaranteed elite or mini-boss chest/package; MVP fight-add card roll; independent crumb roll; runner/hell handling and specials; independent random small box; monster card roll, then **only on card miss** a fresh ore roll, then **only on ore miss** a potion roll at `0.006`; independent Poring Coin roll. Rare materials are direct `gain_material` credits and Poring Coins are direct `found_coin` credits. Equipment is normally rolled on chest collection, not on death. `_next_loot` dequeues already-rolled party Legendary/Unique loot and resolves player choices; it does not decide the per-kill loot category (`main.gd:3961–4010,4046–4058,4104–4126,14176–14234`). `killer.gain_coin(self, 0.25)` is separate from the real Poring Coin roll; see `main.gd:11359–11364,11500–11507` and `player.gd:4128–4148`.

Additional cash: Golden Poring checks start at 70 s, then every 30 eligible seconds with `randf() < 0.06` (timer held while a boss/arena/runner is active). On damage, `step = e.max_hp * 0.06`; each crossed step yields `roundi(90 * danger_reward(danger))` base ground zeny and an 18% small box roll, capped at four step payouts per hit. Capture adds one 5-roll chest and `roundi(2000 * danger_reward(danger))` across 14 **zeny** piles; Tower treasure-floor runner instead drops three piles of `roundi(2000 * 0.05 * danger_reward(danger))` on capture. Ground pickup then applies `loot_mult`, so these runner payouts are doubly danger-scaled, unlike ordinary `LOOT`. Satan Morroc's hoard also applies danger at creation; steal effects call `gain_zeny` with the amount already scaled. `game_data.gd:8764–8765`; `main.gd:1465,11412–11426,15429–15481,15523–15527,7989–7993`; `morroc_event.gd:1045–1052`; `skills.gd:1954`; `legends.gd:112`.

Breakable props are a separate branch: `zeny = randi_range(int(loot.zeny[0]), int(loot.zeny[1]))`; each of three piles pays base `ceili(zeny/3.0)` before ordinary pickup scaling. Wood range `[8,25]`, steel `[40,90]`; potion rolls `.30/.50` and power rolls `.05/.18`; the branch roll `.03/.06` is conditional on no power. Breaking one does not take the normal enemy card/ore/coin path (`main.gd:11312–11314,13352–13373`; `game_data.gd:9157–9160`).

## 3. Star Crumb and Hel Tear

```gdscript
if e.def.get("mvp", false): return GameData.STAR_CRUMB_MVP
if tower != null:
    return tower.hel.crumb_chance() if tower.hel != null else GameData.STAR_CRUMB_KILL
var h = GameData.hell_level(danger)
if festival_mode or h < GameData.STAR_CRUMB_HELL_FROM: return 0.0
return GameData.STAR_CRUMB_HELL + GameData.STAR_CRUMB_HELL_STEP * (h - GameData.STAR_CRUMB_HELL_FROM) + GameData.STAR_CRUMB_OATH_STEP * oath_points()
# caller: not e.summoned and not training and randf() < star_crumb_chance(e) * drop
```

`main.gd:259–270,11407–11411`; `game_data.gd:5715–5736,10165–10166`. MVP `0.035` takes precedence in every mode that reaches this kill path. Normal Tower `0.00085`; normal overworld D1–24 = zero non-MVP; overworld D25–30 = `0.000075 + 0.00004*(h-10) + 0.000015*OathPoints`, `h = maxi(0,d-15)`. Oaths do not unlock crumbs below Hell 10 and `oath_mats` is **not** a crumb multiplier. Tower of Hel uses `0.0013 + 0.00002*int(tower.floor) + 0.000013*oath_points()` (`hel_tower.gd:387–388`; `game_data.gd:164–168`), before `drop`. At zero Oath that is 0.132% at F1 and 0.330% at F100 for non-MVP kills.

Festival does **not** pay on normal kills: one eligible, successful daily claim, `e = mini(checks, 150)`, each check separately rolls `randf() < 0.02` for a crumb and `< 0.01` for a Coin; requires the server claim to return `ok` (`menus.gd:1474–1529`; `save.gd:2254–2262`; `game_data.gd:281–285,5735–5736`). Hel Tower once-only **profile** rewards: F10/30/60/80/90 = +5/+10/+15/+20/+20 crumbs (70 total); F40/100 = +1/+3 Tears, F50 gives a not-owned cosmetic of the highest available rarity with art, or +2 Tears if its eligible pool is empty. No random ordinary/MVP/festival/Oath Tear roll was found; the Hel Tower floor grant is deterministic given unclaimed floor and pool (`tower_run.gd:1092–1104`; `save.gd:1136–1168`; `game_data.gd:172–176`).

[INFERENCE] Expected crumbs are `sum(min(1, p_i * drop_i)) + unclaimed_floor_crumbs + 0.02*claimed_Festival_checks`, summing only eligible kill paths. At `drop=1`, 1,500 eligible non-MVP kills + one MVP = 0.035 at D1, 0.1475 at D25 or 0.4475 at D30 if **all** three runs could reach the same kill count; normal Tower gives 1.310; 1,500 Hel Tower kills at mean floor 50 give 3.485 before milestones. Max Festival claim = 3 expected crumbs and 1.5 Coins. Hel Tear expectation per run is `1*I(unclaimed F40 cleared) + 3*I(unclaimed F100 cleared) + 2*I(unclaimed F50 cleared and eligible cosmetic pool empty)`; repeat clears of claimed floors yield zero.

## 4. Ore rolls and refinement inputs

**Regular ore**: `elif randf() < GameData.ORE_DROP_CHANCE / GameData.coop_spawn(heroes.size()) * drop * oath_mats(): _drop_ore(e.position, 1)` after failed monster card (`ORE_DROP_CHANCE = 0.002`). `GameData.ORES.keys().pick_random()` for each unit; no `danger_boxes`, no `danger_reward` on this roll. Its unconditional per-eligible-kill rate is `[INFERENCE] (1 - P(card)) * min(1,0.002*mats/C)`, half per ore. `ores_found` is a pickup counter, not an RNG: `ores[id] += 1; ores_found[id] += 1`. The gross found count banks at normal `_end_run` even if those ores were used for run refine. `main.gd:11485–11495,13082–13097,14227–14238,15699–15703`; `equipment.gd:180–182,1425–1447`; `game_data.gd:7689–7693`.

**Guaranteed packets / rare ore** (`main.gd:5528–5530,11381–11396`; `mvp_raid.gd:1337–1360`; `game_data.gd:5850–5852`):

```gdscript
var f = n * k
return int(f) + (1 if randf() < f - int(f) else 0) # _mat_count(n,k)
# not-summoned elite: _drop_ore(at, _mat_count(1,mats))
# else not-summoned non-MVP boss: _drop_ore(at, _mat_count(3,mats))
# same boss: randf() < BOSS_ENRICHED_CHANCE * danger_reward(danger) * mats
# actual MVP raid win: _mat_count(MVP_ENRICHED, oath_mats()) one-of-two rolls
# same raid: randf() < MVP_HD_CHANCE * (1.0 + world.player.effects.get("drop_find",0.0)) * world.oath_mats()
```

Each successful enriched/HD roll picks one of its two ores uniformly. `BOSS_ENRICHED_CHANCE = 0.15`, `MVP_ENRICHED = 1`, `MVP_HD_CHANCE = 0.05`; the MVP's guaranteed enriched count does **not** scale with drop-find or danger. The regular fallback ore roll can still fire in addition to an elite/boss packet. Regular, Dark/Light, Morroc and Tower treasure **equipment-chest opening** does not include an ore roll (`main.gd:14176–14226`; `player.gd:4996–5004`; `karma.gd:223–269`); Hell can deliver more eligible enemies/boss packages and raise the mini-boss enriched roll via `danger_reward`, not via an ore-specific Hell multiplier. E.g. with no Oath/drop-find, enriched per eligible mini-boss is `[INFERENCE] 15% at D1, 58.2% at D25, 67.2% at D30`. Box chance is not ore chance.

**Outside kills:** Festival daily pays `e*50_000` zeny, `e*3` **each** normal ore, `e/7` integer enriched draws and `e/50 + Bernoulli(float(e%50)/50)` HD draws (`menus.gd:1504–1529`; `game_data.gd:281–285`); 150 checks = 7,500,000 zeny, 450 + 450 normal ores, 21 enriched and 3 HD, plus the §3 rare rolls. `MATERIALS` has `buy` metadata (Oridecon 2,500 / Elunium 2,000), but no consumer of those prices was found in the effective scripts; these are **not** assumed shop availability or a zeny exchange rate (`game_data.gd:5632–5634`). Transmutation spends `n * times` of `from` for `out(default 1) * times` of `to`, with no zeny/RNG: 10 normal ↔ 1 enriched, 5 enriched ↔ 1 HD, and **one-way** Oridecon → Elunium 1:1 (`game_data.gd:5818–5829`; `menus.gd:24043–24054`).

## 5. Chests, gear tier, Legendaries and Uniques

| Trigger | Ground chests / equipment rolls per successful trigger, `(rolls, bonus)` | Evidence |
|---|---|---|
| Ordinary mob, excluding prize/boss/rose | One `(1,-1)` on `randf() < SMALL_CHEST_CHANCE * killer.card_mult * danger_boxes(danger) * karma.box_mult() * drop / C`; base `0.0015`, `danger_boxes = 1 + 0.05*(d-1)`, Karma box ×1.5 at ≥+50, else ×1 | `main.gd:11440–11444`; `game_data.gd:8637–8638,8714–8716,10298–10299`; `karma.gd:127–128` |
| Feroz/special if eligible | Replaces that chance with `0.12 * drop / C`: no danger, card or Karma box multiplier | `main.gd:11440–11444`; `enemy.gd:310–318`; `game_data.gd:8644–8646` |
| Non-summoned elite / mini-boss | One `(1,0)` / one `(3,1)` respectively. Elite branch wins if both flags are set | `main.gd:11381–11396`; `game_data.gd:8921–8923` |
| Tracked regular stage MVP / route MVP | One `(3,2)` plus a possible separate `(0,2)` explicit unique chest; route MVP marks its normal chest Valkyrie and uses route-unique roll | `main.gd:11515–11547`; `karma.gd:331–342` |
| Tower Lord | One `(5,3)`, `treasure=true`; wings and Hel Requiem are separate awards. Floor event chests are event-dependent | `main.gd:11533–11545`; `game_data.gd:9184`; `tower_events.gd:205–211` |
| Golden Poring outside treasure-floor special | Capture `(5,3)`; per paid damage step 18% `(1,-1)` | `main.gd:11412–11426,15470–15481`; `game_data.gd:8764–8765,8921` |
| Corrupt demon | One special corrupt chest; nominal `(4,2)` but pickup **diverts before gear rolls**. Open = HP −25% (floor 1), Karma −20, +1 Hel Mark and +1 level; purify = Karma +20, +1 feather and +1 level. Autopick/autopilot is 50/50 | `karma.gd:185–269`; `main.gd:14176–14180`; `game_data.gd:8679–8685,8690–8703` |
| Other Hell / side events | Herald `(2,1)`, survived Tide `(2,1)`, MVP shadow `(1,0)`, profaned guardian `(1,1)`; Morroc special chest `(data.chest,3)` with Satan bonus; certain altar/Tower events also call `_drop_chest`. Lucky Soup may spawn `(1,-1)` on eligible crit at 3%, with 30 s cooldown | `main.gd:5852–5855,15252–15272`; `game_data.gd:8469–8471,9961–9979`; `hell_late.gd:322–329,383–385`; `morroc_event.gd:1045`; `altars.gd:696`; `tower_events.gd:205–211` |

`_drop_chest` only creates the pickup and sets visual `tier = clampi(bonus + 1, 0, CHEST_SPRITES.size()-1)`; it is not a rarity roll. At ≥12 merge-eligible ground chests, it replaces the oldest eligible chest and caps merged rolls at 5, retaining the higher bonus and counting downgraded `plain` rolls as `bonus=-1`. Solo small-box cash is `roundi((25 + time/10.0) * player.loot_mult)` on opening; a merged chest with nonnegative bonus does not pay the small-box cash. Lucky Soup adds one opening roll with 25% probability. `main.gd:12977–12984,13046–13076,14190–14216`; `game_data.gd:8469–8471,8633–8638,9163,9184`; `player.gd:4996–5004`.

**Gear roll (`equipment.gd:541–611`)**:

```gdscript
legend_chance = LEGENDARY_CHANCE + legend_bonus + chest_legend + chest_extra if bonus > 0 \
    else (ELITE_LEGENDARY_CHANCE + legend_bonus * 0.2 if bonus == 0 else 0.0)
can_legend = legend_chance > 0.0 and (run_time >= LEGENDARY_MIN_TIME or chest_legend >= 1.0)
max_rank = maxi(1, 1 + int(run_time / RANK_STEP) + bonus)
weights[i] = SLOT_WEIGHTS[i] * pow(1.6, (run_time / 160.0 + bonus) * (i - 1.0) * 0.5)
```

`LEGENDARY_CHANCE=0.0075`, elite `0.0008`, minimum time 200 s, `RANK_STEP=180`, weights `[54,27,13,6]` normalized by sum; `bonus<0` caps drawn slots at 1 and excludes purple, `bonus>0` forces at least 3 for ordinary results, purple also forces 3; item definition `fixed_slots` can override. Eligible same-class ordinary weapons have 3 entries rather than 1; class/weapon/shield restrictions apply. Legendary success needs a nonempty eligible pool (else ordinary fallback); it picks weapons at 30% if both pools exist, and excludes equipped IDs. `chest_legend` = .06 for Satan (permits other classes) or 1 for Tower treasure (also avoids already-stored IDs); `chest_extra` = .017 for Valkyrie. `equipment.gd:186–189,541–611`; `main.gd:14182–14192`; `game_data.gd:1892–1895,7375–7377,7400,7471–7473,7596,8923`.

```gdscript
# set on player equipment at run start (main.gd:1422)
danger_legend = 0.0004 * (d - 1) + 0.0008 * hell_level(d) + 0.0008 * maxi(0, hell_level(d) - 5 + 1)
unique_mult = 2.0 + 0.25 * maxi(0, hell_level(d) - 5 + 1) if hell_level(d) > 0 else 1.0
```

`game_data.gd:10302–10321,7080–7085`. [INFERENCE] On a three-roll ordinary MVP chest after 200 s, with an available pool and no extra roll, `P(≥1 Legendary) = 1-(1-p)^3`: D1 2.23% (`p=0.75%`), D25 8.70% (`p=2.99%`), D30 11.50% (`p=3.99%`). Ground chest count is unchanged by those rarity odds. Party chest rolls per hero, rerolling unaccepted non-unique Legendary results up to six times (`randf() >= 1.0/heroes.size()`), then queues the rare gear for a shared roll. A wholly unclaimed rare item in this channel has a 600 zeny liquidation value, not the manual-sale coin rule (`main.gd:3961–4010,4115–4126`; `game_data.gd:7698`).

**Unique**: `chance *= GameData.unique_mult(danger)` in `_roll_unique`, blocked when stage/job has no ID, in Tower, or already in worn/bag/storage. The tracked map MVP gets `UNIQUE_MVP_CHANCE=0.017`; **opening any ordinary chest with `bonus >= 0`** and no explicit unique gets `UNIQUE_BOSS_CHANCE=0.0012` (including the MVP's ordinary chest). Route MVP instead gets `KARMA_UNIQUE_CHANCE=0.06` for its route ID (Aegis of Reginleif / Corrupt Spear), subject to a party member missing it; its normal chest can still roll the stage unique. `main.gd:11519–11545,11573–11609,14194–14198`; `game_data.gd:7080–7085,8722–8730,11613ff`; `karma.gd:331–342`. [INFERENCE] A single otherwise eligible map-MVP unique drop is 1.7% at D1, 5.95% at D25, 8.075% at D30, before the normal-chest secondary roll. Exact count per run is conditional: `killed_prize_elites + killed_non_MVP_bosses + tracked_MVPs + spawned_unique_chests + other_event_chests + Σ Bernoulli(p_small)`, minus merges on the ground, not a fixed count. §9 gives scheduled event counts and a Prontera example.

## 6. Cards: kill pool, Album and fusion

```gdscript
card_chance = (ELITE_CARD_CHANCE if prize else (FEROCIOUS.card if e.feroz else CARD_DROP_CHANCE)) * danger_cards(danger)
# boss_card = e.is_boss and not e.summoned
if boss_card: card_chance = MVP_CARD_CHANCE if e.def.get("mvp",false) else BOSS_CARD_CHANCE
if not boss_card: card_chance /= coop_spawn(heroes.size())
sure = pity != "" and Save.card_misses(pity) >= pity_at
got = GameData.CARDS.has(card) and not rose and (sure or randf() < card_chance * drop * (1.0 if boss_card else killer.card_mult))
```

`main.gd:11445–11489`; `game_data.gd:8644–8646,8930–8949,10293–10294`. Ordinary 0.038%, Feroz 0.475%, elite 7.6%, non-summoned boss 14.25%, MVP 28.5%, before applicable factors. `danger_cards = 1 + 0.01*(d-1)` only on the non-boss rate; true boss also ignores `card_mult` and `C`. Boss pity forces after 5 misses (6th eligible attempt); non-wild summoned nonboss fight-add, own card, active raid pity after 25 misses (26th); saved counters reset on drop, not on pickup. Independent 30% `_fight_card` roll for nonsummoned eligible raid MVP: pool of deduplicated, valid non-wild cards from ability `mob`/`egg`/`hatch`; prioritizes missing Album cards and resets that card's pity (`main.gd:15492–15513`; `game_data.gd:8944–8945`).

Normal enemies drop their own `MONSTERS[id].card`. In endless or Hell ≥1, an off-stage enemy switches to a uniformly chosen stage pool unless route MVP, Morroc or a summoned non-wild fight add. `_stage_cards` unions stage spawns/events/declared MVP, removes invalid and MVP cards, then uses distinct non-`boss` cards (including elites) or distinct `boss` cards with fallback to the ordinary pool (`main.gd:5162–5217,11464–11473`). Pools below omit the `_card` suffix; `same` means boss falls back to the listed ordinary pool. Source join: `game_data.gd:2214–2700,5121–5352,9188–9744` plus the per-stage event citations in §9.

| Stage | Nonboss pool | Boss pool |
|---|---|---|
| `prontera` | poring, lunatic, fabre, willow, mastering, eclipse, elder_willow | angeling |
| `payon` | spore, poporing, smokie, wolf, bigfoot, elder_willow, eclipse | vagabond_wolf |
| `pay_cave` | zombie, skeleton, archer_skeleton, skel_soldier, munak, bongun, horong, sohee, nine_tail | skeleton_general |
| `orc` | orc_baby, orc_warrior, orc_lady, orc_archer, orc_zombie, high_orc | same |
| `orc_dun` | drainliar, orc_zombie, zenorc, orc_skeleton, orc_archer, high_orc | same |
| `glast` | zombie, whisper, skeleton, archer_skeleton, ghoul, wraith, evil_druid, raydric, khalitzburg | bloody_knight |
| `nameless` | ragged_zombie, hell_poodle, zombie_slaughter, flame_skull, banshee, necromancer | banshee_master |
| `abbey` | disguise, rideword, gibbet, dark_priest, hunter_fly, bloody_murderer | dullahan |
| `culvert` | thief_bug, tarou, plankton, cramp, thara_frog, toad, thief_bug_egg | thief_bug_male |
| `byalan` | kukre, vadon, marina, hydra, marse, obeaune | strouf |
| `turtle` | solider, permeter, freezer, heater, turtle_knight | turtle_champion |
| `pyramid` | matyr, mummy, isis, ghoul, minorous, marduk | ancient_mummy |
| `anthell` | andre, piere, deniro, vitata, argiope | giant_spider |
| `mjolnir` | hornet, steel_chocho, skel_worker, iron_fist, argos, giant_hornet | golem |
| `clock_tower` | punk, alarm, clock, rideword, mimic | owl_duke |
| `niflheim` | quve, hylozoist, gibbet, loli_ruri, bloody_murderer | dullahan |
| `juperos` | venatu, red_venatu, dimik, blue_dimik, green_dimik | archdam |
| `toy_factory` | cookie, cookie_xmas, cruiser, mystcase, marionette, garm_baby | garm |
| `thanatos` | solace, observation, retribution, shelter, zherlthsh | tha_odium |
| `biolab` | ygnizem, whikebain, kavac, rawrel, armaia, seyren, erend, eremes, magaleta, shecil, katrinn | harword |
| `ice_dun` | siroma, snowier, gazeti, ice_titan | furious_snowier |
| `ra_san` | agav, echio, seeker, isilla, vanberk, gremlin, hodremlin, beholder | beholder_master |
| `thor` | magmaring, imp, blazer, explosion, salamander, kasa | lava_golem |

`_take_card` adds to the current hero and calls `Save.add_card`; that increments the permanent copy count and flushes. Unslotted cards sit in the run card bag; `CARD_SELL_ZENY=120` per bag item sold (manual or end), not a payout per Album copy and not a sale of the Album copy. `GameData.card_slots() = BASE_CARD_SLOTS + Save.upgrade_active("card_slot")` = 1 to 4. `fuse_cost = int(FUSE_COST[card_tier(card)])`: 5 normal, 10 boss **or elite**, 20 MVP/unknown; one fusion subtracts this many `card_copies` and adds one `eternal` (no zeny fee). `eternal_free = eternal - eternal_used`; insertion needs space/compatibility; extraction costs 500/1,500/4,000 zeny for those classes. `main.gd:3918–3932,14257–14262,15716–15719`; `player.gd:1211–1225`; `save.gd:573–607,628–689`; `game_data.gd:6015,8114–8117,8926,9122–9133,11327–11328`. [INFERENCE] D1, no modifiers, one eligible card per mob: ~13,158 ordinary kills per 5-copy fuse or ~132 eligible elite kills for 10 copies. With boss pity, `E[kills/copy] = Σ(k=0..5) (1-.1425)^k = 4.228`; ten copies ~42.28 eligible boss kills; MVP 20/.285 ≈70.18 kills ignoring additional quest/fight cards.

## 7. Pets and the three meanings of “coin”

```gdscript
chance = float(GameData.PETS[e.id].drop) * special_mult * drop
if mvp_pet: chance *= 1.0 + GameData.HELL_EGG_STEP * GameData.hell_level(danger)
if not Save.has_pet(e.id) and randf() < chance * (doomed if player.doom else 1.0):
    _drop_item(..., "tame", e.id, GameData.PETS[e.id].tame)
# on pickup: var ok = randf() < float(pet_def.rate)
```

`main.gd:443,13119–13139,13477–13517,14248–14252`; `game_data.gd:1174–1361,5590,10307`. Requires not-summoned, not-rose, and stage mob/route MVP (Tower allows MVP pets too); owned pets are not repeat farm currency. `special_mult=1` in ordinary play. Doom gives ×3 egg chance **only** for MVP pets. Taming can succeed without another living target; if a same-ID living target is found within 10 units the animation may use it and success removes it. Auto Pick resolves the existing tame roll immediately, not automatically successfully.

| Base drop | `rate` | Pet IDs |
|---|---:|---|
| 0.004 | 0.50 | poring |
| 0.004 | 0.45 | lunatic, spore, tarou |
| 0.004 | 0.40 | smokie, marina, permeter |
| 0.004 | 0.35 | sohee, ork_warrior, drainliar, isis, andre |
| 0.004 | 0.30 | whisper, hell_poodle, hunter_fly, steel_chocho, alarm, loli_ruri, cookie_xmas, siroma |
| 0.004 | 0.25 | dimik, observation, kavac, magmaring, isilla |
| 0.03 | 0.75 | The 23 map MVPs in §9, plus reginleif and randgris_fallen |
| 0 | 0 | bon_gun and baphomet_jr are quest-only, not egg rolls |

`game_data.gd:1174–1361` for pet definitions; direct quest pet/card unlock calls `Save.add_pet/add_card` (`quest_run.gd:593–612`; `game_data.gd:8194,8219,8229,8241,8253,8276,8322,8345,8368,8380,8419`). [INFERENCE] Base Poring tame acquisition = 0.20% per eligible kill with pickup; MVP = `0.03*.75*(1+0.05*h)*(3 if Doom else 1)*drop` when unclamped: 2.25% at D1, 3.375% at D25, 3.9375% at D30 without Doom/drop-find.

`PET_COIN_CHANCE = 0.60` is **not** Poring Coin chance. Golden Thief Bug's pet skill has `coins:1.0`; qualifying hits roll `randf() < PET_COIN_CHANCE` for `_runner_coins(...,maxi(1,roundi(float(sk.coins)*(1.0+0.1*h.level))))`, a **zeny** pickup. `player.gd:4128–4148` is a separate class combat coin mechanic; only `found_coin` or an explicit `Save.add_coins` credits the Poring Coin ledger, and `Equipment.cash_in` writes `legend_coin` instead (`game_data.gd:1286–1289,1567`; `main.gd:13729–13781,15523–15527,344–353`; `equipment.gd:958–962`).

## 8. End-of-run banking and Keep

1. **Already profile-side:** local zeny uses `run_zeny += z; if not training: Save.add_zeny(z)`; Poring Coin and rare material awards, Album pickups, tames, Ymir and milestone rewards go directly to Save. A successful stage MVP pulls chests/cards/XP/zeny/ore and waits on prizes and party loot before completion (`main.gd:344–393,11547–11567,11695–11717`). Zeny/rare rewards already saved are not lost on a proper loss. `abandon_run()` calls `_bank_run(false)` but does not perform `_end_run`'s ore credit / sale / daily/keep settlement: do not count those on an abandon (`main.gd:16068–16086`). Co-op settlement uses host ore/XP/MVP counts, and still includes the client coin roll (`main.gd:2960–3022`).
2. **`_end_run` (win or loss):** snapshot eligible worn + bag items for Keep, excluding permanent/lent, credit picked-up `ores_found`, then sell non-permanent bag items. `sell_price = 20 + int(it.slots)*30 + int(it.refine)*15` for normal; Legendary/Unique returns `0`. `sell_from_bag(...,cash)` removes eligible item, moves socketed cards into card bag, sets `last_coins = _cash(it) if cash else 0`. End passes `cash=(legend_coins(it)==0 or lent or training)`: **no automatic legend coins for ordinary transient Legendary/Unique items at run end**. Worn ordinary items enter the Keep list but are not iterated by the bag sale. Bag cards then get `card_bag.size()*120`, and the first eligible positive-zeny run per local date credits `roundi(run_zeny * 0.5)` on the post-sale, post-run-spend total, with no victory gate. `main.gd:15666–15726`; `equipment.gd:322–324,942–962,1223–1240`; `save.gd:611–612`; `game_data.gd:7695–7698,8116`. A normal bag item already sold for zeny can also be selected from the pre-sale Keep snapshot; the selection only charges its Keep fee if not free (`menus.gd:21406–21417,21475–21492`).
3. **`_bank_run`:** guard `_stats_banked`/training, add kill/MVP stats, credit `roundi(player.xp_gained * danger_class_xp(danger) * (1.0 + FEATURED_BONUS if featured else 1.0))`, then record `maxf(run_time,previous.time)`, victory OR previous victory and increment run count. `danger_class_xp = 1.0 + 0.08*(d-1)` is separate from spawn XP. After first rebirth `Save.add_class_xp` caps each run's XP by `roundi(class_climb_xp(class_id) * REBIRTH_LV_RUN_SHARE)`. The end-screen `class_xp` field stores raw run XP, not the multiplied award. Leaderboard score `roundi((roundi(time_s) + zeny / 20.0 + mvps * 600) * (1.0 + 0.25 * (danger - 1)))` (end screen passes `danger + oath_points()`); autopilot/tamper affect submission, not this XP credit. `main.gd:15726–15749,16009–16033`; `save.gd:360–370,739–745`; `game_data.gd:10288–10289`; `leaderboard.gd:575–576`.
4. **Keep requires selection:** `keep_free = victory or run_ymir > 0`; allow 3 free or 1 paid, with `maxi(minimum,ceili(Save.zeny()*share))`. Normal ranks 0/1/2/3 minimum `[0,300,700,1500]`, shares `[0.005,0.005,0.02,0.04]`; Legendary min 4,000 / 15%, Unique min 4,000 / 25%. Wallet basis is total saved zeny, not run profit. Storage cap is `20 + 10 * upgrade_level("kafra_storage") + own_fists` (20–500 ordinary slots; +1 reserved for Fists), so at cap Keep offers a replacement. Storage copy retains ID/slots/extra slots/trait but initializes `refine=0,cards=[]`. `_found_unique` uses `add_to_storage(it,true)` with no Keep action, even over cap. `main.gd:11589–11609,15743–15747`; `menus.gd:21406–21417,21454–21492,21807–21813`; `game_data.gd:5608–5625`; `save.gd:2036–2056,2070–2084`.

## 9. Run shape and rate model

`mvp_at = float(stage.mvp_time) - altars.mod("mvp_early")`; `_event_at` applies the same offset to actual stage-MVP event with debug override handling. A supported stage MVP normally opens a raid portal, so time below is **availability**, not guaranteed clear time; an ongoing tracked MVP reduces ordinary spawn rate to 40%, and some raid phases replace or suspend the field flow. Event array iteration is ordered, not sorted: an event listed behind a later timestamp waits for that earlier list entry. Hard (`d>=8`) adds one same-ID spawn per scheduled `elite` event. `main.gd:4941–4978,5033–5061,5275–5299`; `game_data.gd:7704–7705,10019`.

| Stage | Min D | MVP @ s | Earlier boss-type events @ s | Elite event count (base/hard) | MVP base zeny |
|---|---:|---|---|---:|---:|
| `prontera` | 1 | Baphomet 480 | Angeling 240 | 5/10 | 1,800 |
| `payon` | 2 | Eddga 540 | Vagabond Wolf 240 | 3/6 | 2,700 |
| `pay_cave` | 2 | Moonlight Flower 560 | Skeleton General 250 | 3/6 | 2,560 |
| `orc` | 5 | Orc Hero 570 | — | 4/8 | 3,060 |
| `orc_dun` | 5 | Orc Lord 580 | — | 3/6 | 3,600 |
| `glast` | 7 | Dark Lord 600 | Bloody Knight 250 | 4/8 | 4,000 |
| `nameless` | 8 | Fallen Bishop 620 | Banshee Master 255 | 4/8 | 5,060 |
| `abbey` | 8 | Beelzebub 640 | Dullahan 260 | 4/8 | 6,000 |
| `culvert` | 1 | Golden Thief Bug 520 | Thief Bug Male 240, Thief Bug Egg 275 (event is boss-type; egg not a `boss` definition) | 3/6 | 2,700 |
| `byalan` | 3 | Kraken 540 | Strouf 240 | 3/6 | 2,700 |
| `turtle` | 3 | Turtle General 560 | Turtle Champion 240 | 3/6 | 2,700 |
| `pyramid` | 4 | Osiris 560 | Ancient Mummy 240 | 3/6 | 2,700 |
| `anthell` | 4 | Maya 570 | Giant Spider 240 | 3/6 | 2,700 |
| `mjolnir` | 6 | Mistress 575 | Golem 240 | 3/6 | 2,700 |
| `clock_tower` | 6 | Owl Baron 590 | Owl Duke 240 | 3/6 | 2,700 |
| `niflheim` | 7 | Lord of Death 620 | Dullahan 240 | 3/6 | 2,700 |
| `juperos` | 9 | Apocalypse 630 | Archdam 240 | 3/6 | 2,700 |
| `toy_factory` | 10 | Stormy Knight 600 | Garm 240 | 3/6 | 2,700 |
| `thanatos` | 11 | Memory of Thanatos 640 | Tha Odium 240 | 3/6 | 2,700 |
| `biolab` | 9 | Lord Knight Seyren 650 | Harword 240 | 5/10 | 2,700 |
| `ice_dun` | 12 | Ktullanux 630 | Furious Snowier 240 | 3/6 | 2,700 |
| `ra_san` | 12 | Gloom Under Night 640 | Beholder Master 240 | 4/8 | 2,700 |
| `thor` | 13 | Ifrit 650 | Lava Golem 240 | 4/8 | 2,700 |

Timing/elite table: `game_data.gd:15,9188–9208,9230–9648,9656–9744` (region floors, roster, spawns, ordered events; egg definition `game_data.gd:2437–2440`). Base MVP zeny = `LOOT.zeny * LOOT.count * LOOT.chance` (`game_data.gd:5355–5536`). Min D and unlocked range are enforced by `stage_danger_range` (`game_data.gd:10130–10161`).

### Scaling formulas

```gdscript
# GameData, game_data.gd:9759–9808,10165–10166,10196–10242,10264–10289
h = maxi(0, d - 16 + 1); b = mini(d, 15); ramp = clampf(t / 300.0, 0.0, 1.0)
crowd_curve = pow(1.24,b-1) if h>0 else pow(1.24,mini(b,4)-1)*pow(1.34,maxi(0,b-4))
hell_mult = pow(2.0,mini(h,10))*pow(2.15,maxi(0,h-10))
danger_hp = trim * 1.1 * (crowd_curve if crowd else pow(1.2,b-1)) \
    * lerpf(1.0,hell_mult*(hell_squeeze(d) if squeeze else 1.0),ramp)
# trim = 0.9 for h>=10 else 1; hell_squeeze = HELL_HP_SQUEEZE[h] (clamped index)
danger_rate = (1.0+0.15*(b-1)) * (1.0+0.15*h*ramp)
danger_reward = 1.0 + 0.12*(d-1)
danger_xp = pow(pow(1.13,d-1),0.5)
mvp_danger_hp = 1.0 if h>0 else lerpf(1.5,2.0,float(d-1)/14.0)
```

`spawn_rate(t)=1.0+t/170.0`, ordinary `scale_hp(t)=1.0+t/150.0`, tough `scale_boss_hp(t)=1.0+t/600.0` (`game_data.gd:11350–11361`). `e.max_hp = def.hp * time_hp_scale * mob_norm(id).x * danger_hp(...)` before other modifiers; `e.xp = maxi(1, roundi(e.xp * norm.z * danger_xp(danger)))`. `mob_norm` compares Prontera's unweighted spawn-row average to each stage's average, using the **first** stage containing that mob; boss classification for the `crowd` curve is `not def.has("boss")`, so elites can have tough time scaling and still use crowd danger HP. Actual field rate: `spawn_rate * danger_rate * (1+altars.mod("spawn")) * (1+player.curse) * lerpf(1,0.7,opening()) * C`, then boss `.4`, Hell Tide and endless multipliers when applicable. `opening()` is `clampf(1.0-time/180.0,0,1)` on tier-1 D≤2 unless endless/Tower; these early raid MVPs also use additional HP ×0.8. `main.gd:4921–4952,5402–5506`; `game_data.gd:10330–10355,11339–11346`; `mvp_raid.gd:475–479`. At cap 175 desktop / 170 web, normal spawns can fail; crowd fusion starts near 25% of cap, aggregates HP/XP but still gives one death roll per resulting enemy (`main.gd:5402–5420,5502–5506`; `game_data.gd:9211–9227`).

```gdscript
crowd_zeny_mult = maxf(0.45, 1.0 / (1.0 + maxf(0.0, float(kills - 20000)) / 73000.0))
```

`game_data.gd:10248–10254`; `main.gd:13106–13112`. No thinning to 20k kills; after that ordinary gross pile value goes down (not card/material rolls, and not boss/elite cash). [INFERENCE] 93,000 kills is ×0.5, and the floor starts around 109,223 kills. Long endless production cannot extrapolate early zeny/kill forever.

**Endless.** After the first MVP, normal/manual play can choose to end or `continue_endless()` via victory choice/raid exits; Auto Pick ends on victory unless the explicit exception applies (`main.gd:11702–11717,15625–15641`; `menus.gd:16047`; `mvp_raid.gd:1382ff`). Endless sets first event `time + ENDLESS_EVERY*0.5` = +20 s, later +40 s, every fourth event = same stage MVP; non-MVP `_endless_pick` uniformly chooses a **record** from all stage event arrays excluding MVPs, not a uniform mob/stage pool. Rush jumps to the next fourth index, and Morroc finale can preempt. Per event count `n`, rate `*= 1+0.10*n`; ordinary/MVP HP `*= pow(1.36/1.24 respectively,n)` and damage `*= pow(1.22/1.14 respectively,n)`; movement `*= 1+(0.09/0.05 respectively)*n`; MVP HP additionally `*= pow(1.3,run_ymir)` and from event count ≥8 `*= 0.5`. Off-map mixed spawn timer accumulates at current rate, interval 1.1, batch `randi_range(2,4)`; Feroz interval 12–18 s in endless vs 45–60 normal / 30–40 hard, further affected by altar/Karma/Oaths. Death in endless counts as victory. `main.gd:4947–4952,4985–5030,5067–5139,5450–5467,15625–15662`; `game_data.gd:1603–1621,1653,8642–8646`.

### Expected rate at fixed DPS

[INFERENCE] **Reproducible crowd baseline, not a clear-time benchmark.** Solo Prontera, t = 0–480 s (MVP availability), damage budget `DPS=300` effective HP removed per game second, same at all dangers, no XP-driven DPS growth; perfect pickups of all modeled streams; `card_mult=drop=oath_mats=1`, no Oaths, upgrades, curse, featured/Frenzy, Karma, daily, gear sales, pet, runner, special/boss/ring kills, Hell added streams, misses to pathing, backlog, fusion or UI downtime. Use a midpoint for each second `t=j+0.5` and active spawn rows only (`main.gd:4941–4978`; `game_data.gd:9188–9193`). Fractional kills represent expected flow, not actual spawn timing. All ordinary HP per id `hp_i = MONSTERS[i].hp * mob_norm(i).x * scale_hp(t) * danger_hp(d,hell_ramp(t),true,true)`; `s_i=rate(t,d)*batch_i/every_i`, `k_i=s_i*min(1,300/Σ(s_i*hp_i))`. Unused budget in one second is not carried. Then:

```text
zeny/min = (60/T) Σ_t Σ_i k_i * LOOT[i].chance * LOOT[i].count * roundi(pile_value * danger_reward(d))
box cash/min = (60/T) Σ_t Σ_i k_i * (0.0015 * danger_boxes(d)) * roundi((25+t/10)*danger_reward(d))
normal material/min = (60/T) Σ_t Σ_i k_i * 0.002 * (1 - 0.00038*danger_cards(d))
```

[INFERENCE] These combine code in §2/4/5 and assume all four Prontera stream types have a valid card. Material/min is unweighted total regular Oridecon+Elunium; each is half. No assumed exchange rate between ores, Crumbs and Tears. The crumb column is a **per-run** value from these kills only; add `.035*drop` for one eligible MVP beyond the model. 

| Danger | Hell | Expected ordinary kills | Ground zeny/min | Small-box cash/min | Total modeled zeny/min | Normal ore/min | Crowd crumbs / window |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 1,523.12 | 346.82 | 14.17 | 360.99 | 0.3806 | 0 |
| 5 | 0 | 876.50 | 278.96 | 12.82 | 291.78 | 0.2190 | 0 |
| 10 | 0 | 254.70 | 107.90 | 5.85 | 113.74 | 0.06365 | 0 |
| 15 | 0 | 58.95 | 32.28 | 2.04 | 34.33 | 0.01473 | 0 |
| 20 | 5 | 18.34 | 10.92 | 0.67 | 11.59 | 0.004584 | 0 |
| 25 | 10 | 1.53 | 1.01 | 0.068 | 1.08 | 0.000383 | 0.000115 |
| 30 | 15 | 0.04 | 0.031 | 0.002 | 0.033 | 0.000010 | 0.000011 |

[INFERENCE] D1 maximizes both combined modeled zeny/min and normal ores/min on the seven-point grid; D25 maximizes modeled non-MVP Crumbs because D30 throughput collapses at fixed 300 DPS. D2 is a near tie for Prontera cash if including boxes (~361.07 vs ~360.99 zeny/min), but not regular ore. At 1,000 fixed DPS the same grid favors D5 cash from ordinary piles and D1 ores; at 10,000 it favors D10 pile cash and D5 ores. These are break-even examples, not a universal difficulty setting. For any runtime measured inputs, add scheduled payouts only when killed/collected, divide by actual **end time**, and distinguish a per-kill improvement from throughput; e.g. moving from D1 to D5 needs at least `1/1.48=67.6%` retention of ordinary pre-multiplier cash/min before rounding/bonuses; ore requires approximately unchanged kills/min, since the base ore roll is unchanged.

[INFERENCE] **Full-clear conditional ledger example (D1 Prontera):** add all five scheduled elite chests, one Angeling chest and one Baphomet chest to the crowd model; scheduled cash adds `2*120+2*120+200+360+1800=2,840` zeny; fixed ores add `5+3=8`, enriched EV `1+0.15=1.15`, HD `.05`, Ymir `1`, MVP Coin `.03`, MVP crumb `.035`. Small boxes from crowd ≈`1523.12*.0015=2.28`; ordinary ground equipment boxes ≈9.28 (11 guaranteed-event rolls + 2.28 ordinary-box rolls), plus unique boxes/special opportunities excluded. Ordinary mob Poring coins ≈`1523.12*0.00004=0.061` before the cap. Cash subtotal `8*(346.82+14.17)+2840≈5,728` before sale/side payouts/daily; ore subtotal `8+8*.3806≈11.04` before fallback ores from those scheduled enemies. Rates from this subtotal are `5728/(8+raid_minutes)` and `11.04/(8+raid_minutes)` if the raid adds no modeled crowd, but expenses, survivability and boss damage-budget contention change the actual result. No guarantee those elites or the MVP are killable at the baseline crowd DPS.

[INFERENCE] For a measured-run forecast, form a resource vector instead of assigning arbitrary zeny values to rare drops: `run_zeny_before_daily = ground + small_box_cash + steals + sales + other_run_cashes - run_spend`; `profile_zeny_delta = run_zeny_before_daily + I(eligible_positive_daily)*roundi(0.5*run_zeny_before_daily) - keep_spend`; add separately claimed Festival zeny only once. `profile_basic_ores = I(end_settlement)*picked_up_ore_count`, `profile_enriched/HD/crumbs = sum(direct_awards)`; include stage/mode milestones as separate deterministic terms. `E[mob_coins] = E[min(3,Σ Bernoulli(p_i))]` over otherwise eligible kills; exact equivalent `Σ_{j=1..3} P(Σ Bernoulli(p_i) >= j)` before adding separate MVP and daily/checkpoint Coin sources. Divide each component by observed cycle time including raid, menu and reset overhead for wall-clock rates. Code basis `main.gd:344–412,11485–11507,15699–15725`; `menus.gd:1504–1529,21475–21490`; `mvp_raid.gd:1337–1360`.

## 10. Cheap versus rich: thresholds and recurring sinks

Permanent upgrade next level `int(round(UPGRADES[id].cost * 1.4 * pow(level + 1, 1.35) / 10.0) * 10)`, where level is currently owned; active mods accumulate `mods[k]*lv` and upgrades can be disabled except storage and cart (`game_data.gd:5546–5604,11272–11279,11315–11328`; `menus.gd:19099–19108`). Representative starting cost → total to cap below; totals are `[INFERENCE]` arithmetic from that formula.

| Upgrade | Economic combat/reward lever | Levels | First zeny | Total zeny |
|---|---|---:|---:|---:|
| Bubble Gum | +0.15 zeny additive-mod and +0.20 `card_mult` per lvl | 5 | 3,920 | 91,080 |
| Blessing | +6% damage per lvl | 5 | 3,920 | 91,080 |
| Magnificat | +4% haste per lvl | 5 | 4,900 | 113,850 |
| Battle Manual | +6% XP per lvl | 5 | 4,480 | 104,090 |
| Greed | +15% collection radius per lvl; half applies to objects/cards/boxes | 10 | 3,500 | 373,350 |
| Card Album | One more Album slot/lvl | 3 | 8,400 | 66,830 |
| Kafra Storage | +10 storage/lvl | 48 | 8,400 | 32,709,640 |
| Pushcart | +1 initial equipment slot/class/lvl | 6 | 11,200 | 386,060 |
| Bloody Branch | Curse +0.1/lvl; spawn and HP ×`1+curse`, zeny add `2*curse`, XP add `0.7*curse` | 5 | 2,800 | 65,060 |
| Red / Blue Gemstone, each | Additional multi-projectile/hit or melee hit/lvl | 2 | 28,000 | 99,380 |
| Yggdrasil Leaf | Extra run revival/lvl | 2 | 21,000 | 74,530 |
| Doom | ×3 MVP egg roll, +30% boss damage; survival penalty | 1 | 1,400,000 | 1,400,000 |
| Increase AGI | +4% movement/lvl | 5 | 3,500 | 81,320 |
| Gloria / Angelus / Increase HP Recovery, each | +3% crit / +1 defense / +0.40 HP per sec, per lvl | 5 | 3,920 | 91,080 |
| Yggdrasil Berry / Memorize, each | +8% HP / +8% duration per lvl | 5 | 4,480 | 104,090 |
| Yellow Gemstone | +6% skill area/lvl | 5 | 4,900 | 113,850 |
| Fury / Plant Bottle / Venom Knife, each | +10% crit dmg / +12% summon dmg / +10% status dmg per lvl | 5 | 4,200 | 97,600 |
| Vulture's Eye | +8% projectile speed/lvl | 5 | 3,080 | 71,560 |
| Telescope | +1 `reach` mod/lvl | 6 | 6,300 | 217,160 |

- **Keep cost turns wealth-dependent** without implying better combat: `[INFERENCE]` percentage overtakes the minimum above 60,000/35,000/37,500 zeny for ordinary ranks 1/2/3, ~26,667 for Legendary, 16,000 for Unique (rank 0 has no positive minimum). One more Kafra slot upgrade is +10 slots, not a fee on each item when kept free. (`menus.gd:21807–21813`; `game_data.gd:5608–5625`.)
- **Run refine vs rich refine:** temporary refining spends one run ore; normal failure −1, smith failure accumulates luck instead. In town, from `it.refine >= 7` normal ore is barred; `p_enriched = minf(1.0,base + (1.0-base)*0.30)`, `p_HD = minf(1.0,base + (1.0-base)*0.55)`. Fee `int(REFINE_FEE[rate_key] * Equipment.fee_mult(it) * 5.0 * pow(1.4,refine) * (5.0 if guarded else 1.0))`; base tables W1/W2/W3/W4/armor = 100/300/600/1,000/500, ×2 unique. Nonfixed, unguarded failure destroys stored gear; guarded/fixed failure −1 refine. W4/armor +9→+10 base `.09`, `[INFERENCE]` enriched `.363`, HD `.5905`; protected ordinary W4 +9 fee ≈516,526 zeny/try. `equipment.gd:337–338,401–403,476–503,1425–1447`; `menus.gd:25404–25475`; `game_data.gd:5832–5848,7085,7670–7677`.
- **Sockets / grades:** normal additional socket fee `[2000,3000,4500,6000]` by original slots, chance table `[.60,.45,.30]` by capped item rank; Legendary costs `[8000,16000] * fee_mult` plus `[1,2]` matching enriched ore, odds `[.20,.12]`. Grade from +10: weapons D/C/B/A/S cost `[200k,500k,1.2M,3M,6M]` and `[40,80,150,250,400]` basic ores; HD `[0,0,0,1,2]`; success `[.90,.70,.50,.35,.25]`, failed try pays all inputs without grade loss. Accessories use cost multiplier .25, other gradeable nonweapons .5, with integer/1k rounding in `grade_cost`. `equipment.gd:352–376`; `menus.gd:23778–23814,25293–25311`; `game_data.gd:5752–5758,5774–5788,8119–8126`.
- **Other zeny sinks:** class unlock `spend(int(CLASSES[class_id].unlock_cost))`, configured 20,000–30,000 for paid classes; Sage `int(round(SAGE_UPGRADES[id].cost * pow(level + 1, 1.35) / 10.0) * 10)`; Chef table capacity level 2 costs 1M and level 3 costs 3M, serving unlocked dishes itself does not charge zeny. `Save.unset_eternal` costs 500/1,500/4,000; gacha 20M/spin if not using 5 Poring Coins. Zeny-using skills (e.g. Mammonite, Cart Termination and Throw Zeny) debit `roundi(v.call("zeny_cost") * maxf(0.0,1.0-float(p.effects.get("zeny_discount",0.0))))` from both run and profile wallet; Golden Axe's Mammonite branch uses wallet-based scaling instead of the cost. Do not count spent zeny again in the daily bonus. `save.gd:668–676,704–717,1978–1995`; `game_data.gd:616,640,680,710,852,3253–3257,4038–4041,4083–4087,5900–5901,8447`; `menus.gd:2590–2640,19094–19108`; `skills.gd:730–748`; `main.gd:398–412,15723–15725`; `gacha_panel.gd:485–506`.

## Optimal farm target

All rankings are `[INFERENCE]` from the cited formulas, not runtime clears. Choose by the constrained resource; a cheap-safe collect/sell loop, a real MVP clear and a daily claim optimize different things.

1. **Daily account cash/raw ore, if eligible: Emperium Festival (its own rules, not a map-danger target).** 50,000 zeny plus 3 of each ore per bankable check; it dominates ordinary farming for the claim, not once the daily is consumed. The ordinary daily +50% is separate (§3/4/8).
2. **Ordinary map materials / safe MVP fragments:** `(prontera,1)` first, `(payon,2)` second for regular-ore crowd flow, `(culvert,1)` next distinct map in the 300-DPS model (~.381/.364/.337 regular ores/min, respectively). For Ymir and the fixed MVP enriched/HD/Coin chances, fastest reliable actual raid win wins: Prontera 480 s availability and gentle MVP HP, then Culvert 520 s, then Payon/Byalan 540 s; prefer Culvert if its MVP dies >40 s sooner or its loot is the goal. No direct danger bonus for Ymir or the guaranteed MVP enriched packet.
3. **Repeatable ordinary ground cash in this fixed-DPS projection:** `(turtle,3)` ~608 zeny/min, `(pyramid,4)` ~594, `(culvert,1)` ~574 for distinct maps, before boxes, scheduled payouts and real pickup losses. They use the same spawn/HP model given above and each stage's own `LOOT` and `mob_norm`. For a clear rather than a clock-limited crowd run, Culvert competes strongly on earlier portal, guaranteed elite/mini-boss chests and 2,700 base MVP cash; verify portal entry, clear time and pickup rather than extrapolating from map tier. Use date feature (+25%) and Frenzy (+30% wallet and, where allowed, 1.3× game-clock speed, not a flat wall-time multiplier during menu/raid pauses; `main.gd:14780–14794`; `game_data.gd:11378–11386`) only if they preserve clear/collect reliability. Low danger wins when HP limits kill flow; once spawn-limited, raising danger or curse pays until the throughput loss overtakes the wallet multiplier.
4. **Legendaries / specific map Unique or rare MVP pet:** pick the map that owns the ID; among available reliably clearable runs compare `(target_stage,30)` against `25`, `20` and the fastest low-D clear. D30 gives highest per-opening rarity and egg chance, but not necessarily highest per minute. For 3-roll MVP Lego at D30 vs D25, for example, 11.50% vs 8.70% only tolerates ~1.32× longer cycle at equal clear/loot pickup probability; actual map-unique rolls 8.075% vs 5.95% tolerate ~1.36×. For high-D enriched, mini-boss routes with genuine `boss` definitions benefit from danger; `orc`/`orc_dun` lack a scheduled true mini-boss before MVP. Card targets usually favor the quickest map with the actual mob: nonboss odds rise only +1% relative per danger and boss card base does not rise at all.
5. **Crumbs/Tears/Hel Requiem:** `(Tower of Hel, deepest repeatable route)` for Tears/Requiem first clears and strongest non-MVP crumb chance; regular Tower next once milestones are exhausted if its kills/min compensate for its lower crumb probability. For overworld crumbs `(prontera,25)` is the threshold candidate; `(target_stage,30)` only beats D25 when it retains enough kills/min: at zero Oath/drop-find `0.000075/0.000275 ≈ 27.3%` after isolating MVPs. Neither high difficulty nor Oath points substitutes for reaching D25 in the overworld. At low danger, easy, short MVP cycles still award the same 3.5% crumb roll, while **ordinary** overworld kills cannot drop one.
