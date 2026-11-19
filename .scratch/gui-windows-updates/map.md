# Map: GUI + Windows + updates

Label: wayfinder:map

## Destination

A spec ready for `/to-spec`: **Midgard Farm as one application for Linux and Windows.** The operator installs it, starts AFK farming and reads the night's results without a terminal. It survives game updates and app updates by itself.

## Notes

- Domain: `GLOSSARY.md`. In particular, **Game update** and **App update** are different things; never write a bare "update". `afk-reliability` (spec and ADRs 0001–0004) is the existing AFK contract: supervisor, checkpoint, commands, quarantine.
- Skills: grilling tickets use `grilling` + `domain-modeling`; prototype tickets use `prototype`; research tickets use `research`. Code questions: `docs/agents/farmer-map.md`.
- Research branches are local only (no git remote): `research/<name>`, created through `git worktree add`. Never switch branches in the main checkout, because a live AFK farm may be running from it.
- Settled while charting (operator, 2026-11-19):
  - One map, one spec for GUI, Windows and updates together.
  - The only user is the operator, on their own Linux machine and one Windows machine.
  - The GUI is the operator's only interface; the terminal is for development only.
  - Both kinds of updates are in scope. Game update handling is the priority: today every game update drops the night farm into quarantine.
  - The stack is free (criteria: behaves the same on Linux and Windows, maintained by one person). The in-game farmer stays GDScript.
  - Windows has full parity, including night AFK under a supervisor, on its own local profile.
  - The two machines have independent profiles; nothing is synced between them.
  - On a game update the app rebuilds the farmer patch, installs it and runs a smoke check by itself. It asks the operator only on failure.
  - Only the game itself downloads the official patch (the operator accepts it while playing). The app notices the result. If the build is stale it says so plainly: "start the game and accept the update".
  - AFK lives as an OS background service. The window is a remote control: closing it does not stop the night.
- Deferred by the operator (2026-11-19): [08: Network isolation on Windows](issues/08-windows-network-isolation.md) and [09: How the window talks to the AFK service](issues/09-gui-supervisor-protocol.md). The map hands off to `/to-spec` with each ticket's recorded spec default: [spec.md](../midgard-farm-app/spec.md).

## Decisions so far

<!-- one line per closed ticket -->

- [01: Windows platform facts for the farmer](issues/01-windows-platform-facts.md): Windows has native equivalents for every Linux mechanism (GDRE CLI, LockFileEx, Job Objects, firewall/WFP, Task Scheduler, toasts). Constraints for the spec: Godot's rename on Windows is not atomic (delete then move); a hard exit gives code 0 even on failure, so the outcome is decided by the terminal status; the profile path must be confirmed (03); AFK survives a closed window but not sign-out or sleep.
- [02: Is the farmer patch shared between Linux and Windows?](issues/02-farmer-patch-cross-platform.md): the official patch is the same on both OSes and the farmer pck carries no native code (confirmed by 03). Superseded on sourcing by 06 Q17: each machine builds its own pck; copying would be the sync this map rules out.
- [06: How the app handles a game update](issues/06-game-update-flow.md): read from `state.json` before every launch; the supervisor builds, smokes in the sandbox, installs, then runs the attempt, with no failure counted. A failure quarantines as `build_failed` / `anchors_broken` / `smoke_failed` per (official patch sha, farmer hash), leaving the official patch mounted; new term **Game reinstall**; ADR 0005. Each machine builds its own farmer patch.
- [05: What the operator sees](issues/05-gui-shape.md): four screens (AFK session, History, Updates, Quarantine), no settings screen; phase and heartbeat first; Abort alone confirms; quarantine shows one next action.
- [03: Windows test bench](issues/03-windows-bench.md): gpu-pc, Windows 11 25H2, admin, no Python, never sleeps on AC; `user://` is `Ragnarok Survivors` (base 0.1.272; find the profile by markers, not name). Official patch and bridge identical to Linux; GDRE on Windows builds a byte-identical farmer patch in 16 s, one offline run passed and the official state was restored.
- [04: Application stack](issues/04-stack.md): Python 3.13 + PySide6/QML in one package (`core`/`platform`/`gui`). Linux: systemd user unit; Windows: Task Scheduler logon task (packaging and build revised by 07). Stdlib + PySide6 only; bash and the C++ `gui/` deleted after pytest parity; ADR 0006.
- [07: How the app updates itself](issues/07-app-update.md): a private GitHub repo; Actions builds both PyInstaller onedirs from a `v*` tag. The service installs a new version into a versioned user dir in a quiet window and reverts by itself if it is not ready in 60 s. The farmer is rebuilt only when the **Farmer hash** changes; ADR 0007.

## Not yet specified

- **Night history.** Beyond the session list from 05: rewards/hour compared by preset or character, how far back to keep, how much to show.
- **Notifications.** Desktop on both OSes plus a phone (ntfy is already in the supervisor). Which events to send and how to configure them from the GUI.
- **Verification on Windows.** Settled: the one-run smoke runs on both OSes; `platform` pytest runs on gpu-pc (04). Open: whether the soak and the other `verify` scenarios run on Windows, and the sandbox profile there.
- **First install and uninstall (both OSes).** How the first onedir reaches a machine and where the read-only PAT is entered; registering and removing the service; restoring the official patch on uninstall (06 Q15); where the app and the logs live.

## Out of scope

- Distributing the app to other people or publishing it: one operator, their own machines (Q2 while charting).
- Syncing a profile between machines (Q7).
- The app downloading or decrypting the official patch itself (Q9).
- macOS and Android.
- Rewriting the in-game controller (draft, keep, maintenance, target choice).
