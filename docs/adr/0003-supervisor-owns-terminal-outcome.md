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
- Watch mode on Linux can report a successful, flushed `done` status before the game aborts in native window shutdown. A recorded windowed run finished settlement and published `exit_code: 0`; the game then logged leaked GLES3 buffers and glibc's `double free or corruption (!prev)`. The coredump shows the main thread aborting through the allocator from the stripped game binary. The original invalid free or corruption was not localized. The supervisor accepts the actual `SIGABRT` only for a windowed launch that already reported terminal success, retaining the raw signal in its attempt record. Closing the window without terminal success still follows the normal exit and restart policy.
- systemd remains a thin boot/restart layer.
- A fresh heartbeat proves liveness, not progress. The supervisor treats a run whose game time has not advanced for 3 minutes (20 minutes in a raid, where the clock can legitimately freeze) as `run_stalled`. It aborts that run, restarts the same AFK session and counts the attempt towards quarantine. Leaving the run phase, entering or leaving a raid, or advancing game time starts a new watch window.
- `python -m midgard_farm.health` uses the same progress rule and heartbeat timeout. It ages the supervisor's last progress observation on the same boot's monotonic clock when available; otherwise it compares its own samples and marks the result unconfirmed.
