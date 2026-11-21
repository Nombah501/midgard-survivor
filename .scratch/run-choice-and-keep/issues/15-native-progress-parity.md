# 15: Record AFK runs in local progression like manual runs

**What to build:** The game's autopilot flag makes native settlement skip local progression that a manual run records (evidence: local://progress-loss.md from the 2026-11-21 investigation): **Album → History** entries, Hell title and oath progress, and altar achievement counters. Rewards themselves are banked. The operator wants farmer runs to count in these local records exactly like his manual runs.

Rules:
- Only local progression the game records for a manual run of the same outcome; never anything a manual run would not get, never character preparation (ADR 0008).
- Never submit farmer runs online: leaderboards, cloud, Epic/EOS. The game already marks autopilot records `online: false`; that must hold.
- Prefer the game's own recording code paths (e.g. run them for the farmer's settlement with the autopilot gate lifted only for those calls) over re-implementing the bookkeeping; whichever is chosen, it must be idempotent across crash recovery (Run ID, ADR 0001).

**Blocked by:** 12, 13, 14 (same files).

**Status:** ready-for-agent

- [x] Inventory in 0.2.7 of every local record skipped under autopilot, with file:line, recorded in this ticket.
- [x] A real D30/37 sandbox win added one Album → History entry, the Hell class/location, oath best 37, and five altar takes (+5 total; per-run best 5). The post-settlement restart kept the same records; the corrected judge passed on the real run artifacts.
- [x] Native online branches are unchanged; the sandbox settlement observed no board HTTP request, co-op mode, cloud revision change or new queued world-chat feat.
- [ ] Static checks, mypy (linux, win32), pytest suites pass.

## Official 0.2.7 inventory

Decompiled with GDRE 2.7.4 (bytecode `ebc36a7`); scanned the scripts in the official patch.

| Local record | Gate and native writer | Farmer settlement |
| --- | --- | --- |
| Album → History (`history`, at most 50 rows) | `main.gd:16458–16477` skips `Leaderboard.log_run`; manual abandon has the same gate at `main.gd:16828–16829`. `leaderboard.gd:490–502` checks 30 game seconds, training and player presence before `save.gd:2278–2284`. | Invoke `_keep_history` only; `log_run` would also reach online RPCs (`leaderboard.gd:465–487`). Abort without settlement remains unchanged. |
| Hell maps/classes, titles including Phoenix, oath best and title notices | World call gate `main.gd:16479`; `titles.gd:201–232` checks outcome, MVPs, eligibility and runs `news()` (`titles.gd:181–194`); `save.gd:1799–1806` retains the maximum oath score. The native tamper check is at `main.gd:16459–16464`. | Use the native plausibility check and `Titles.after_run`; lift autopilot only synchronously for this call. Suppress its world-chat dispatch; preserve any earlier queued feats. |
| `bare_hands` and `close_call` MVP feats | `main.gd:11965` calls `Titles.mvp_feats` exactly at the MVP kill; `titles.gd:77–84` checks autopilot, downed state, HP and weapon at that instant. | Deliberate non-parity: the kill-time inputs cannot be reconstructed from settlement, and the approved design does not inject game scripts. |
| `stats.altars`, `stats.altars_run` | `altars.gd:411–419` counts native non-restoring `take` events; `altars.gd:34` clears the array per run. `karma.gd:302` has no counter write. | Apply the native bulk update used at `main.gd:3149–3151` to `Altars.taken.size()`; counters for runs that never settle are not replayed after a crash. |

The original submission branches (`main.gd:16465–16476`) and end-screen `online: false` (`main.gd:16485–16486`) are untouched. These local writers do not call cloud or EOS. Recovery accounts for the settled Run ID without repeating native records.
As with keep, a crash after the game banks rewards but before the farmer flushes its keep step may omit the local end records; recovery never synthesizes or repeats them.
