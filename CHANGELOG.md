# Changelog

## [0.4.8] - 2026-11-26

- Game 0.2.11: the farmer now meets the Wandering Kafra (Sage upgrade) that the game hides from autopilot. It walks to her as soon as she appears, ahead of altars, and takes the first help she offers from this list: Kafra Sweep, Golden Poring, Level 99 Power, Emperium Blessing.
- Game 0.2.11: after the 40:00 finale the farmer fights Morroc II, III... instead of ending the run. Each win pays Elunium, Oridecon and Star Crumbs, and a fall still ends the run as a victory.
- Corrupt Chests are always opened instead of a coin flip between opening and purifying: each Hel mark gives +8% damage and a level. The farmer opens a chest as soon as it drops, waiting until the hero is at half HP or more because opening costs 25% of max HP.

## [0.4.7] - 2026-11-25

- Smarter farming spot: the farmer scores open ground by how much of the area where enemies spawn (15–22 tiles out) has a straight path to it, and holds the best spot within 32 tiles. Enemies then come straight at the hero instead of walking around walls, rocks and mazes. It moves only for a clearly better spot, and after a short errand or dodge it walks back instead of picking a new one.

## [0.4.6] - 2026-11-25

- The farmer holds a spot: between altars and MVPs it picks the nearest open ground (7×7 tiles free, reachable in a straight line), walks there and stands still so the horde comes to it, instead of roaming. After an altar it holds near that altar rather than walking back.

## [0.4.5] - 2026-11-25

- Melee heroes fight instead of kiting: the game's own steering treats the whole Acolyte line (Monk, Champion) as ranged casters and keeps them 4–7 units from enemies, out of mace reach. The farmer now steers by the basic attack's real reach, picks lone enemies first and skips enemies behind a wall.
- Early game: until hero level 20 the farmer only takes altars close by and not inside a horde, and ignores the golden runner, so a fragile hero levels up near where it stands.

## [0.4.4] - 2026-11-25

- Altars come first: the farmer heads for the best altar before the golden runner and pickups, and takes Baldur as soon as it can (an interrupted Baldur gets one more try at the MVP portal).
- No more detours for loot: the magnet pulls gems, zeny and ores, the pet fetches chests and an MVP win pulls cards, so the farmer only walks to pet eggs (and to chests when no pet fetches them).

## [0.4.3] - 2026-11-25

- Presets are gone: pick a **Mode** in the window, *Endless until the final boss* or *Short runs (until the MVP)*. A saved 0.4.x choice opens as Endless with Valhalla.
- **Route** in the window for the karma portal after each regular MVP: Valhalla, Hel (Fallen Randgris via Niflheim) or Random each run. On the Hel side the farmer also takes Hel altars.
- All locations in turn starts each new session at a random unlocked location, then continues in order.

## [0.4.2] - 2026-11-23

- Champion (Acolyte, Monk branch) in the character list.
- Experimental: 8× speed switch in the window; overrides the preset's speed from the next run. Tower keeps its native speed.

## [0.4.1] - 2026-11-22

- App update checks reach the signed channel: the update host rejected the default Python User-Agent (Cloudflare error 1010), so 0.4.0 could not check for updates. Everything else is as in 0.4.0.

## [0.4.0] - 2026-11-22

- New window design: one dark palette on Linux and Windows, the session's runs drawn as a band (win, loss, in progress, aborted), pinned action bar, layouts that fit small windows.
- Endless Tower and Torre de Hel as run choices: the farmer spends the most-levelled unlocked Tower snapshot, one per Start, and climbs until death or Finish. Farmer runs now leave one Tower snapshot (the best one) without pushing out your own.
- Morning report: Latest session with elapsed time, downtime, restarts and the stop reason, plus a Night summary from 18:00 to 12:00.
- App updates come from the project's own signed channel: no GitHub token. Check for updates and read the changelog in Updates.
- Health tab: on-demand diagnostics with next steps and a Repair farmer pack button.
- Rewards are recorded only after the game has really saved them; Pause now survives a crash or service restart.
- A caption under Show game window: windowed farming roughly halves income.
- Arena timings (entry, first damage, kill) in logs and the run journal.

## [0.3.9] - 0.3.x summary

- Shipped packaged Linux and Windows apps with a supervised AFK service, a desktop window and versioned App updates.
- Added run choice and location rotation, maintenance and wishlist controls, and an option to show the game window during AFK.
- Improved Hell rotation, navigation and MVP hazard avoidance; recorded cause of falls and kept legendary items the Operator does not already own when requested.
