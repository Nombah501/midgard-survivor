# The supervisor owns the AFK terminal outcome

Status: accepted

The external supervisor, not the launcher script or the game, decides whether an exit is a clean finish, a crash or a quarantine. The farmer writes a terminal status and a heartbeat; the supervisor reads them and applies restart, backoff, quarantine and notification policy. systemd only keeps the supervisor alive.

## Considered Options

- **systemd-only restart:** rejected; systemd can restart a dead process but cannot distinguish a clean finish from a silent failure, inspect a game heartbeat or quarantine a crash loop.
- **Launcher script decides:** rejected; the launcher is too close to the child and cannot survive the child's failure mode.
- **External supervisor:** chosen; one policy owner that can be tested without the game.

## Consequences

- The farmer status contract becomes an external interface, not a debug dump.
- Supervisor decisions are testable with a fake child and status files.
- systemd remains a thin boot/restart layer.
