# The supervisor rebuilds the farmer patch before an attempt

Status: accepted

A Game update deletes the farmer patch, and today the next supervised attempt hits preflight exit 78 and quarantines, losing the night. Before each attempt the supervisor now checks `state.json`; on a Game update it rebuilds the farmer patch, runs a one-run smoke in the sandbox and only then installs into the real profile and starts the attempt, without counting a failure. This extends ADR 0003: the supervisor still owns the terminal outcome, and now also this one pre-launch step, because AFK runs as a background service with no window to do it.

## Considered Options

- **Quarantine as today, operator rebuilds:** rejected; it turns the commonest cause of lost nights into a manual step.
- **The GUI window rebuilds:** rejected; the window may be closed while AFK runs.
- **Retry failed rebuilds with backoff:** rejected; build failures are deterministic.

## Consequences

- A failed rebuild quarantines at once with `build_failed`, `anchors_broken` or `smoke_failed`, and the game stays on the official patch.
- That quarantine is keyed by (official patch sha, farmer hash): it lifts on "Check again", on a new Game update, or on an App update that changes the farmer. Every other preflight 78 and every crash-loop quarantine stays final.
- Each machine builds its own farmer patch; nothing is copied between machines.
