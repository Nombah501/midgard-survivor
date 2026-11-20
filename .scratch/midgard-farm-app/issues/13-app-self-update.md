# 13: App self-update

**What to build:** The service checks the private releases at start and once a day, downloads and verifies a new version, switches `current` in a quiet window (no AFK session, game closed) and requires a readiness marker within 60 s. Otherwise it reverts, marks the version bad and notifies. The current and one previous version are kept; manual rollback works; a changed Farmer hash triggers the Game update pipeline.

**Blocked by:** 07, 12.

**Status:** ready-for-human (one real tag-to-update round trip on both machines)

- [x] A running AFK session is never interrupted; the switch waits for its terminal outcome.
- [x] A version that fails to write the readiness marker is reverted automatically and never retried.
- [x] A failed check is quiet; only a rejected token notifies.
- [ ] Covered at the service seam with fake release archives; one real tag-to-update round trip is done on both machines. (Fake coverage complete.)
- [x] ADR 0007 holds as written.

## Comments

- 2026-11-20 (from ticket 11): release asset contract.
  - Each `v<version>` tag on the private repo carries `midgard-farm-<version>-linux-x86_64.tar.gz` and `midgard-farm-<version>-windows-x86_64.zip`, each with a `<asset>.sha256` sidecar.
  - Each archive contains a top-level `midgard-farm/` onedir with `midgard-farm-service[.exe]` and `midgard-farm[.exe]`.
  - Prereleases (PEP 440 pre segment) are GitHub prereleases; the updater ignores them.
  - The version at runtime is `midgard_farm.assets.version()`.
  - The service's self-check is `midgard-farm-service --self-check <out.json>` (`packaging/service_entry.py`); use it, or the readiness marker, for the 60 s ready check.
  - First real release: v0.1.0 (`b91de77`).
- 2026-11-20 (from ticket 12): New archives also contain console `midgard-farm-setup[.exe]` and a standalone onedir at `launcher/midgard-farm-launcher[.exe]`. Setup copies the latter to `<app-data>/bin/` and registers it once; do not update it as part of automatic App updates. The stable launcher reads `<app-data>/current` (UTF-8 `<version>\n`) on startup and runs the service under `<app-data>/versions/<version>/`. The fine-grained read-only token is stored in `<app-data>/release-token`.
- 2026-11-20: The installed service checks GitHub on startup and every 24 hours, downloads and SHA-256-verifies the stable release, and applies it only at the supervisor's idle boundary with the game closed. A separate, time-bounded user watchdog runs from the old executable and starts the new service through the stable launcher. It commits only a fresh readiness marker, or rolls back, marks the failed release bad and notifies. The Updates screen and `midgard-farm-service rollback-app` can select the previous release. The existing Game update pipeline sees the selected Farmer hash after update and rollback. Fake release-service tests cover both watchdog recovery outcomes, quiet-window behavior, bad archives, token handling and Farmer hash rebuilds.
- 2026-11-20: Run a real tag-to-update round trip on Linux and Windows and verify the scheduler handoff, check status, and previous-release rollback. If a watchdog and the selected executable both fail before the latter reaches startup, run setup from the previous version's folder (or its unpacked release archive), then start the service. The stable launcher remains unchanged.
- 2026-11-20 (review fixes): Setup shares the watchdog lock. A switch interrupted before pointer publication does not blacklist the untried release. Both automatic updates and manual rollback require readiness from the live instance; failed manual rollback restores the source without blacklisting. The cache keys verification by both release asset IDs, notification recovery persists its own receipt, and history is appended by the running service under `service.lock`.
- 2026-11-20 (re-review fixes): Stage selection and validation now happen under the update lock. Changed or incomplete replacement assets invalidate the previously verified bundle before download. Linux resets the unit start-limit counters before queuing restart and a confirmed first-start refusal does not blacklist a release that never started. Windows handles synchronous scheduler errors; after an accepted Windows restart, its last-run result is not used to override a missing readiness marker.
