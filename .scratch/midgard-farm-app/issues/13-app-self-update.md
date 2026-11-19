# 13: App self-update

**What to build:** The service checks the private releases at start and once a day, downloads and verifies a new version, switches `current` in a quiet window (no AFK session, game closed) and requires a readiness marker within 60 s. Otherwise it reverts, marks the version bad and notifies. The current and one previous version are kept; manual rollback works; a changed Farmer hash triggers the Game update pipeline.

**Blocked by:** 07, 12.

**Status:** ready-for-agent

- [ ] A running AFK session is never interrupted; the switch waits for its terminal outcome.
- [ ] A version that fails to write the readiness marker is reverted automatically and never retried.
- [ ] A failed check is quiet; only a rejected token notifies.
- [ ] Covered at the service seam with fake release archives; one real tag-to-update round trip is done on both machines.
- [ ] ADR 0007 holds as written.
