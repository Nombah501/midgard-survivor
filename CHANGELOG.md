# Changelog

## [Unreleased]

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
