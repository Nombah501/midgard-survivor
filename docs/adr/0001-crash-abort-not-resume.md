# Abort the current run after a crash; do not auto-resume in v1

Status: accepted

If the farmer or the game dies mid-run, the next AFK session starts a new run instead of calling `RunSave.resume`. A wrong resume can double-settle rewards or restore an inconsistent run save; losing at most one run is cheaper than corrupting a long session. Resume may be revisited only after a sandbox prototype proves that the game's own resume path is safe for a farmer-driven run.

## Considered Options

- **Resume via `RunSave.resume`:** rejected for v1 because the farmer's run state, settlement boundary and the game's run save are not proven to agree after a hard kill.
- **Abort and start a new run:** chosen. The profile keeps effects the game already banked; the session continues with accurate totals.

## Consequences

- At most one run is lost on a crash.
- The session checkpoint must reconcile totals and avoid re-settling a run that was already banked.
- A future resume feature needs its own prototype and ADR.
