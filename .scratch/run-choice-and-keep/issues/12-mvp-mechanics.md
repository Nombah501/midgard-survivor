# 12: Survive every MVP mechanic in the Hell rotation

**What to build:** The first 6-hour live Hell rotation (0.3.7, Assassin Cross, all locations in turn, D30, 37 oaths) won 22 of 26 runs. All four defeats ran out of revives (Yggdrasil leaves) after 2–8 falls:

| Location | Death at | Killed by | Mechanic | Falls before |
|---|---|---|---|---|
| Payon Forest | 22:00 | Valkyrie Reginleif | Lanzas de Valhalla | 8 |
| Orc Dungeon | 18:01 | Orc Lord | Terremoto | 7 |
| Nameless Island | 4:42 | Fallen Bishop Hibram | Golpe aplastante | 2 |
| Turtle Island | 14:20 | Valkyrie Reginleif | Lanzas de Valhalla | 6 |

Only Caída de Valhalla (ticket 10) and field boss charges (ticket 11) are dodged today. Production logs record only the final killing blow, so the causes of earlier falls are unknown.

1. **Every fall is logged** in production (`PLAYER_FELL t= by= what= piercing= revives_left=`) and counted per mechanic in the run journal, so the next night shows exactly what costs leaves.
2. **Dodge every MVP mechanic that downs the hero.** Inventory all MVP and Valkyrie mechanics in 0.2.5 (telegraph shape, timing, piercing/Doom), starting with Lanzas de Valhalla, Orc Lord Terremoto and Hibram Golpe aplastante, and give the farmer avoidance for each telegraphed one, generalising the Caída/charge avoidance where possible (one hazard-avoidance layer fed by the game's telegraphs, not one special case per boss).

**Blocked by:** 11.

**Status:** resolved

- [x] Production `PLAYER_FELL` logging with cause and per-run fall counts by mechanic in the journal and history.
- [x] An inventory of MVP mechanics (0.2.5) with piercing/Doom status and avoidance approach, recorded in the ticket.
- [ ] Real drills (like `valkyrie-drill`) for Lanzas de Valhalla, Terremoto and Golpe aplastante: red before, green after (0 hits over ≥5 trials each).
- [ ] Full `hell-rotation` on at least Payon Forest, Orc Dungeon, Nameless Island and Turtle Island at D30/37 to the finale with 0 deaths; `valkyrie-drill`, `field-charge-drill`, `blocked-portal`, `one-run` still pass.
- [x] Static checks, mypy (linux, win32), pytest suites pass.

Spec: [`../spec.md`](../spec.md).

## Mechanic inventory — official 0.2.5

Static evidence: the 0.2.5 `GameData.RAIDS`, `MvpRaid`, `RaidTrials`, `BossBrain` and `Player.take_damage`. Timings are game seconds at normal cast settings; an arena tick can round any deadline up. The three priority telegraphs and the native fall hooks were also checked against the 0.2.7 decompile.

| Priority | Native tell and hit | Piercing / Doom | Avoidance |
|---|---|---|---|
| Reginleif, **Lanzas de Valhalla** | Two interleaved sets of strips, 2.6 wide, strike at 1.4 s and +1.0 s. Collision is cross-lane position only; the ends of the drawn lines are not escape routes. | Yes / immediate down | Enter an unmarked lane inside the walkable arena and switch on the actual second-wave state. |
| Orc Lord, **Terremoto** (`quake`) | Locks three radius-3 circles at cast start: one on the solo hero, two near them. All strike after 1.2 s. Distinct from the field pet nova and Turtle General's same-named line-of-sight check. | Yes / immediate down | Exit the union of all marked circles, not just the first. |
| Hibram, **Golpe aplastante** | Field `BossBrain.slam`: radius-3.5 circle on the hero, plus two nearby circles below 50% boss HP, locked for 1.1 s. One hit total per hero, 1.6× boss damage. The name distinguishes this field hit from Hibram's arena abilities. | No / no | Exit the union via walkable ground, overriding idle/altar/loot movement. |

### Shared shapes and responses

**D** = piercing, triggers Doom with a valid MVP source; **T** = piercing periodic damage scaled by Doom, not an instant down (`doom_tick`); **N** = no direct piercing hit. `lethal` is not the damage flag: `_hit_pct`, `_hit_dmg` and `_hit_all` all use piercing even without that data key. Active invulnerability can still suppress contact damage; damage taken and hitbox contacts must be measured separately.

| Game mechanic | Shape / timing rule | Status | Counterplay |
|---|---|---|---|
| `slam`, `rain` | Locked XZ discs; at least one on the solo hero; all resolve at cast end | D | Leave the union, staying inside walkable arena. |
| `charge` | Locked heading, then dash for 0.85 s at speed 17, contact at boss radius + 1 | D | Leave the swept corridor before the dash. The field version is N with a 0.8 s tell. |
| `cone` | Boss position and facing lock at cast start; finite radius and angle | D | Move behind, beyond the radius, or off the nearer side. |
| `volley`, `spokes` | Two alternating parallel strips or interleaved outward rays; the second wave has its own timer | D | Use the active wave's safe lanes or spaces between rays. |
| `starfall` | First hero-position sample at 0.30 s, then one every `step`; each locked disc strikes 1.0 s later | D | Keep orbiting inside the rim and away from obstacles until the last strike. |
| `wall` | Moving cross-arena sheet after `lead`, at `speed`; one contact per wall; an extra wall in the final phase | D | Enter the marked gap before the sheet reaches the hero. |
| `sweep`, `ns_twin_sweep`, `clock` | Rotating ray(s) after cast, or 12 successive marked wedges at `step` intervals | D | Follow behind the active beam or just-resolved wedge; leave the pivot. |
| `puddles`, `brand` | Cast draws circles then leaves damaging pools; timed player mark drops a persistent pool with grace | T | Leave pools; drop personal marks at the rim and exit. |
| `vortex` | Widening disc with pull; dangerous 0.5 s pulses after its growth threshold | D | Run beyond the final radius while countering pull. |
| `los`, `shield` | Arena-wide at end of cast, except pillar shadows / radius-2.3 sanctuary | D | Reach verified cover or enter sanctuary. |
| `platforms`, `tether`, `still` | Periodic damage outside pads (`0.5 s`), outside tether (`0.5 s`), or on violating stand/move instructions (`1 s`) | T | Stand on a pad, stay inside tether, or honor the motion instruction. |
| `orb` | Pursuit begins immediately; 1.0 s to arm boss-side collision, not hero-side collision | D | Kite through the boss without crossing the orb. |
| `cleanse`, `mark` | Cleanse within radius 2 for 0.5 s; marker failure at deadline if bubbles remain | Cleanse T, mark D | Reach sanctuary; route through all bubbles before the countdown. |
| `towers`, `polar`, `snap`, `runes`, `ns_brand` | Countdown: soak/claim circles, reach the assigned color or rune, or satisfy motion/position instruction | D on failure | Use the native objective goal; hold towers for 1 s to claim them. |
| `doom` | Windup drops HP to 1; healing orbs spawn for the pulse countdown | D even after healing: the pulse still goes through the native Doom path | Collect healing orbs for non-Doom; in Doom this is a damage/defense check, not a spatial dodge. |
| `bombs`, `break`, `guard`, `eggs`, `summon`, `ice` | Timed attackable objectives, frontal guard, add waves, or slipperiness zones | Bombs and break D on failure; guard/eggs/summon/ice N | Kill priority targets before the timer, flank the guard, avoid ice. |

### Arena roster and timings

`ability:mechanic time`: seconds to strike or duration, `first/+second` for two waves, `step/count` for starfall, `lead/speed` (units/s) for walls, `cast/duration` for persistent hazards. The roster lists every configured `GameData.RAIDS` ability, including both Valkyries.

| MVP | Native ability IDs and timing |
|---|---|
| `baphomet` | brandish:cone 1.1; charge:charge 0.8; lov:shield 5; summon; curse:cleanse; darkness:rain 1.4; rifts:spokes 1.4/1; towers:towers 7; scythe_guard:guard 9 |
| `eddga` | slam:slam 1.2; roar:los 3.5; summon; charge:charge 0.7; burn:platforms 4/6; rifts:spokes 1.4/1; tether:tether 9; stalk:snap 3 |
| `moonlight` | fire:rain 1.2; charm:mark 11; summon; bell:orb 13; eggs:eggs 9; rifts:spokes 1.4/1; puddles:puddles 1.5/12 |
| `ork_hero` | cleave:cone 1; volley:los 3.5; ritual:eggs 12; summon; charge:charge 0.7; rifts:spokes 1.4/1; lanes:volley 1.6/1.2 |
| `orc_lord` | quake:slam 1.2; bombs:bombs 10; summon; lava:platforms 4/6; rifts:spokes 1.4/1; wall:wall 1.6/5; orders:snap 3 |
| `dark_lord` | meteor:shield 5; tombs:eggs 10; soul:orb 13; frost:ice 14; hail:rain 1.4; curse:cleanse; rifts:spokes 1.4/1; still:still 6; brand:brand 6; twilight:polar 5.5 |
| `fallen_bishop` | requiem:shield 5; cross:rain 1.3; graves:eggs 10; souls:orb 13; confession:mark 11; summon; curse:cleanse; rifts:spokes 1.4/1; tether:tether 9; brand:brand 6 |
| `beelzebub` | swarm:summon; plague:los 3.5; hellfire:rain 1.3; devour:mark 11; dive:charge 0.7; rot:cleanse; rifts:spokes 1.4/1; wall:wall 1.6/5; vortex:vortex 5.5; hell_judge:doom 4 |
| `golden_bug` | rain:rain 1.2; charge:charge 0.8; summon; bombs:bombs 10; rifts:spokes 1.4/1; puddles:puddles 1.5/12; glint:snap 3 |
| `kraken` | slam:slam 1.1; wave:los 3.5; summon; ice:ice 12; rifts:spokes 1.4/1; wall:wall 1.6/5; vortex:vortex 5.5; abyss_eye:snap 3 |
| `turtle_general` | starfall:starfall 0.55/6; cleave:cone 1; quake:los 3.5; summon; charge:charge 0.7; rifts:spokes 1.4/1; still:still 6 |
| `osiris` | rain:rain 1.3; curse:cleanse; summon; soul:orb 13; rifts:spokes 1.4/1; wall:wall 1.6/5; brand:brand 6 |
| `maya` | starfall:starfall 0.55/6; slam:slam 1.2; acid:los 3.5; summon; charge:charge 0.8; rifts:spokes 1.4/1; towers:towers 7; cave_in:snap 3 |
| `mistress` | starfall:starfall 0.55/6; rain:rain 1.1; mark:mark 11; summon; charge:charge 0.7; rifts:spokes 1.4/1; volley:volley 1.6/1.2; buzz:snap 3 |
| `owl_baron` | rain:rain 1.2; bolt:los 3.5; summon; orb:orb 13; rifts:spokes 1.4/1; clock:clock 0.8 |
| `lord_of_death` | cone:cone 1; dark:shield 5; summon; curse:cleanse; rifts:spokes 1.4/1; sweep:sweep 1.8/5; vortex:vortex 6; brand:brand 6; reaper_guard:guard 9; hell_judge:doom 4 |
| `apocalips` | slam:slam 1.1; laser:los 3.5; summon; bombs:bombs 10; rifts:spokes 1.4/1; sweep:sweep 1.8/5; shutdown:runes 14 |
| `knight_of_windstorm` | lance:cone 1; charge:charge 0.8; gust:los 3.5; summon; rifts:spokes 1.4/1; frost:ice 14; wall:wall 1.6/5; storm_guard:guard 9 |
| `thanatos` | scythe:cone 1; rain:rain 1.2; curse:cleanse; rifts:spokes 1.4/1; souls:towers 7; chain:tether 9; soul_judge:polar 5.5; memories:runes 14 |
| `reginleif` | spear:cone 1; spears:volley 1.4/1; pillars:rain 1.2; starfall:starfall 0.55/6; judgment:los 3.5; aegis:break 12; einherjar:summon; seals:towers 7; charge:charge 0.6; scales:polar 5.5 |
| `randgris_fallen` | spear:cone 0.9; blood:rain 1.2; hel_brand:brand 6; embrace:vortex 6; mark:mark 11; souls:break 11; fallen:summon; chains:tether 9; hel_scales:polar 5.5 |
| `l_seyren` | bash:slam 1.1; pierce:charge 0.7; brandish:cone 1; clones:summon; rifts:spokes 1.4/1; lanes:volley 1.6/1.2; berserk:sweep 1.8/5 |
| `ifrit` | claw:cone 1; charge:charge 0.8; eruption:rain 1.2; summon; hellfire:los 3.5; rifts:spokes 1.4/1; lava:platforms 4/6; wall:wall 1.6/5; brand:brand 6; inferno:doom 4 |
| `gloom` | swipe:cone 1; eyes:rain 1.2; night:shield 5; summon; curse:cleanse; rifts:spokes 1.4/1; seals:towers 7; abyss:vortex 6; night_guard:guard 9; eclipse:polar 5.5 |
| `ktullanux` | breath:cone 1; stomp:slam 1.1; blizzard:los 3.5; summon; rifts:spokes 1.4/1; icicles:starfall 0.55/6; frost:ice 14; still:still 6; glacier:break 12 |
| `naght_sieger` | starfall:starfall 0.55/6; flame_slash:cone 1; fire_rifts:spokes 1.3/0.9; inferno:brand 6; ice_slash:cone 1; lances:volley 1.5/1.1; frozen_time:still 5; night_charge:charge 0.7; twin_sweep:ns_twin_sweep 1.8/5.5; brand:ns_brand 7; hours:clock 0.55; seals:towers 7; black_wall:wall 1.5/5.5; eclipse:shield 5; no_return:doom 4; summit_runes:runes 14 |

Other encounters: field `BossBrain` also casts a 0.8 s `Embestida` windup followed by the same 0.85 s charge (N), or an immediate add wave / self-heal (N). The Orc Lord pet `Terremoto` is not the hostile raid ability. Morroc uses separate `MorrocEvent` rather than `GameData.RAIDS`:

| Morroc attack | Native shape / timing and response |
|---|---|
| Descent / impact | Radius-4 landing mark at the end of the omen; leave the marked circle. |
| Guadaña Infernal / Garras del Renacido | 1.1 / 0.9 s aimed cones; sidestep. |
| Grietas del Abismo | 1.5 s spoke wave and another +0.9 s; move between rays. |
| Juicio Infernal / Abrazo del Abismo | 2.6 s countdown; get beyond radius 8 despite pull or inside radius 3.2, respectively. |
| Sello de la Desesperación | Personal mark for 5 s; drop at the rim, leave the blast radius and the remaining pools (16 s). |
| Alas del Apocalipsis / Embestida del Renacido | Three telegraphed dash lines, each after 1.0 / 0.9 s; sidestep each. |
| Lluvia de Calaveras / Danza de Calaveras (finale) | Seven targeted falls (0.9 s cast, first fall after another 1.4 s, then 0.14 s spacing); keep moving. Four orbiting skulls last 8 s with 1 s warmup; stay beyond their outer orbit. |
| Incarnations | Kill adds within 18 s; avoid the radius-2.6 rain while alive and the radius-4.5 crash tells. |

Morroc `_hit_pct` passes piercing and does not mark `doom_tick`; Doom applies on those hits when the source has the MVP flag. Morroc's native movement goals are unchanged by the shared arena and field avoidance.

**0.2.7 delta:** Baphomet's `scythe_guard` was replaced by `abyss_leap`: 0.6 s rise, 2.6 s shadow tracking at 4.5 units/s, 0.8 s locked radius-3.7 landing hit, then two six-ray waves 0.9 s apart (D). The shared layer reads the tracked disc and the active rift angle. 0.2.7 also changed vortex pulses from D to T. Timings for the three priority mechanics are unchanged.

### Real 0.2.7 evidence

In the sandbox baseline with native steering, Lanzas de Valhalla made one hitbox contact in five trials and killed the hero. The production fall hook emitted `PLAYER_FELL t=0.0 by=Valkyrie Reginleif what=Lanzas de Valhalla piercing=true revives_left=0` and the journal counted `{"Lanzas de Valhalla":1}`. The pre-avoidance baseline also hit all five Hibram slam trials. The first candidate avoided both Lanzas waves in all five trials and all five quake strikes, but still took five slams. A native motion trace showed that endpoint-only scoring kept switching between safe-looking moves without crossing the circle's edge. The escape scoring now also rewards immediate progress out of the hitbox.

With immediate escape progress enabled, the D30/37 `mvp-mechanics-drill` passed on 0.2.7: five trials per mechanic, ten spear waves, five quakes, and five slams, with zero hitbox contacts, damage hits, deaths, or journaled falls. The first quake trial starts at the +Z rim to exercise the native escape direction when its marked circle is centered on the hero.

## Comments

- Coordinator, 2026-11-22: finales on candidate 45e284f (official 0.2.7, D30/37): Orc Dungeon win with 0 falls, Nameless Island win (1 fall: Vuelo), Turtle Island win (1 Caída, 4 Morroc Sentencia at the finale), Payon Forest defeat at 18:41 after 7 Caída falls and 1 Eddga. Likely cause under investigation: Caída strikes run on an unclamped SceneTreeTimer while hero movement uses the capped frame delta at speed 4/game_speed 3, so heavy frames leave the hero short of the safe spot. The operator rated the remaining rare deaths non-critical and asked to ship; the Payon finale box stays unticked as a known issue, the ticket is closed by operator decision.
