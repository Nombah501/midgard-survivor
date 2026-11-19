# Run AFK sessions with OS-level network isolation

Status: accepted

The `offline` config flag only changes the Save name; CloudSave can still queue a sync before or after the farmer's process. AFK sessions therefore run the game with OS-level network isolation (`PrivateNetwork=yes` or `unshare -n`) so a cloud sync cannot race a long unattended session. Cloud progress is synced manually between sessions when needed.

## Considered Options

- **Rely on `offline:true`:** rejected; it is not a network gate.
- **Pause CloudSave in code:** rejected for v1; more invasive and still dependent on every cloud entry point checking the flag.
- **OS-level isolation:** chosen; one boundary outside the game, no per-call auditing.

## Consequences

- Cloud progress does not update during an AFK session.
- The operator must sync manually between sessions if cloud is required.
