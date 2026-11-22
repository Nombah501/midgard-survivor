# Release 0.4 — plan draft (2026-11-22)

Sources: Operator wishes (`.scratch/future-ideas/`), window redesign (runestone, `.impeccable/surfaces/`), analysis reports in `/home/n501/ms-research/` (FarmDataAnalyst, GameModesResearch, ProductGapsReview, CodeHealthAudit). Status: needs Operator approval.

## Evidence summary

- D30/37: 63/69 finale wins excluding Finish requests (91.3%), 199M net zeny/h over 17.8 run-hours; latest rotation 36/37, 211.5M/h. 77 started / 77 settled, 0 lost, 0 restarts.
- Late-run slowdown: Endless MVP intervals take 68.5% of run time; matched intervals slow 40→63 s from early to late in 37/37 runs; 4,908 HITCH events in the latest attempt.
- Windowed Toy Factory win 28:18 at 99.8M/h vs headless 15:35–15:41 at ~200M/h ([INFERENCE] rendering is a major cause).
- Arena: boss spawns 0.2×radius behind centre, hero enters 0.6×radius opposite; KARMA_ROUTE→Valkyrie kill median 2 s, p95 7 s: no measurable walking time to win back.
- Endless Tower / Torre de Hel consume a saved run snapshot; the named Loadout loader rewrites preparation (ADR 0008 conflict) and must stay out.
- Risks found in code: settlement checkpoints after unchecked `Save.flush()`; Pause held only in memory (crash while paused can start a new run); quarantine written before terminal outcome.
- Dev loop: pre-push ~25–30 min (serial, every commit); `test_verify` registry test 115 s; GUI readiness races caused v0.3.8 CI failure.

## Proposed scope

| # | Item | Size | Risk |
|---|---|---|---|
| A | Window redesign (runestone) incl. run band | L | med |
| B | Settlement durability: verify the save before each checkpoint | M | high |
| C | Pause survives restart; quarantine/outcome single commit | M | med |
| D | Late-run slowdown: profile and fix the farmer-side cause | M | low to measure |
| E | Warn in the window that "Show game window" halves income | S | low |
| F | Morning report: "Latest session" + real night window, downtime, restarts | M | low |
| G | Own update channel (signed manifest, private repo, Check for updates, changelog) + Linux cutover to packaged service | L | high |
| H | Arena entry: instrument arena entry → first hit → kill only; no movement change | S | low |
| I | Endless Tower (normal) as its own run choice with an Operator-chosen snapshot | L | high |
| J | Dev loop: parallel pre-push, verify test without 42 workers, GUI readiness helper | S–M | low |
| K | Disk caps: `.sandbox`, patch-install backups | S | med |
| L | Doctor: read-only diagnostics + game-update digest-aware repair | M | med |
| M | Death regressions for attacks that ended runs (Lanzas, Terremoto, Golpe aplastante) | M | med |
