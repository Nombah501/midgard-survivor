# 06: How the app handles a game update

Type: grilling
Status: resolved
Blocked by: 01, 02

## Question

What exactly happens from the moment a game update has replaced the farmer patch until AFK farms again on the new farmer patch?

Settled while charting: the app rebuilds, installs and smoke-checks by itself, and asks only on failure. The game itself downloads the official patch.

Still open:
- When to notice it: at app start, before every supervised launch, by watching `state.json`, or in run.sh preflight as today (exit 78).
- What "smoke" means and how long it may take: `verify --one-run` in a sandbox, or less.
- What happens to a running AFK and to quarantine. Should a supervisor quarantined on "official patch changed" recover by itself after a successful rebuild?
- What is shown and sent to the operator in each outcome (success, rebuild failed, the farmer's anchors broke and the code needs fixing).
- How the known-good backup, `official-state.json` and the rollback to the official patch work.

## Prep

Facts (with file:line) and draft grilling questions, each with a recommendation: [assets/06-game-update-prep.md](../assets/06-game-update-prep.md).
How to use: read the Facts section, then go through the rounds. "Yes" accepts the ➡️ recommendation; name another option to override. The accepted answers go into `## Answer`.

## Answer

Grilled with the operator, 2026-11-19. Every recommendation accepted; Q17 added during the session. Decision record: [ADR 0005](../../../docs/adr/0005-supervisor-rebuilds-farmer-patch.md).

**Gist:** the app and the supervisor read the Game update from `state.json` before every launch; the supervisor builds, smokes in the sandbox, then installs, all before the attempt, without counting a failure. A failure quarantines with one of three new reasons, keyed by (official patch sha, farmer hash; refined by 07 Q5), and leaves the game on the official patch. Each machine builds its own farmer patch.


- **Q1 detection:** at app start, before Start AFK, on window focus and before every supervisor attempt, by comparing `state.json` with `patch_farmer.info` (no hashing). Preflight exit 78 stays as the safety net. No file watcher.
- **Q2 states:** *current*, **Game update**, *farmer patch removed or stale*, **Game reinstall** (new glossary term). Only a Game update triggers the automatic rebuild; removed/stale reinstalls without rebuilding; a Game reinstall does nothing automatic and shows "start the game and accept the update".
- **Q3 game running:** wait until the game process is gone (plus a short grace for the updater's self-restart), show "waiting for the game to close", no prompt.
- **Q4 smoke:** `verify.sh --one-run` in the sandbox, 300 s hard limit.
- **Q5 strictness:** one retry; the second failure counts. No supervised scenarios.
- **Q6 order:** build → smoke in the sandbox → install into the real profile → start. On failure the real profile is untouched and `state.json` stays official as the game wrote it.
- **Q7 who rebuilds:** the supervisor runs the Q1 check before every attempt; on a Game update it builds, smokes, installs and then runs the attempt. A pre-launch step, not a failure: no failure count.
- **Q8 failure:** immediate quarantine with a new reason `build_failed`, `anchors_broken` or `smoke_failed`; one attempt per official patch sha until the operator presses "Check again". Other 78s and crash-loop quarantines stay final. Record as ADR 0005 (supervisor rebuilds the farmer patch before an attempt).
- **Q10 outcomes:** four, classified by failure class, not message text: *Game update handled*, *build failed*, *anchors broke*, *smoke failed*.
- **Q13 farmer-patch fallback:** none for a Game update; the official patch is the only fallback. Pack rollback for an App update belongs to 07.
- **Q14 `official-state.json`:** refreshed on every detected Game update from the official state the game just wrote, before any install.
- **Q16 orphaned official patch:** left alone.
- **Q9 session (moot, fact):** `pause` keeps the game process alive (ADR 0004) and there is one game per machine, so a Game update cannot land inside an AFK session. The rebuild always runs before the first attempt; within a session `state.json` does not change between attempts.
- **Q11 shown/sent:** success → a history line ("Game update 0.2.3 → 0.2.4 handled, smoke OK, 3 min"), plus one low-priority notification only if no operator was present. Failure → high-priority desktop + ntfy notification: outcome name, game version, one-line reason (last `build:`/`run:` line), log path; *anchors broke* adds "the farmer needs a code fix; the game is fine on the official patch".
- **Q12 leaving the quarantine:** Start AFK refuses with the outcome and reason. The block is keyed by (official patch sha, app version): it lifts on "Check again", on a new Game update, or on an App update. *Refined by 07 Q5: the key is (official patch sha, farmer hash), so only an App update that changes the farmer lifts it.*
- **Q15 rollback to the official patch:** restore `state.json` from `official-state.json`, delete the farmer patch; check the named official file exists, else "start the game and accept the update"; refuse while the game runs.
- **Q17 Windows source of the farmer patch:** every machine builds its own (headless GDRE CLI on Windows, ticket 01). Copying from Linux would be the sync the map rules out. Ticket 03 step 7 becomes "GDRE on Windows builds a pck that loads".
