# 13: App self-update

**What to build:** The service checks the private releases at start and once a day, downloads and verifies a new version, switches `current` in a quiet window (no AFK session, game closed) and requires a readiness marker within 60 s. Otherwise it reverts, marks the version bad and notifies. The current and one previous version are kept; manual rollback works; a changed Farmer hash triggers the Game update pipeline.

**Blocked by:** 07, 12.

**Status:** ready-for-agent

- [ ] A running AFK session is never interrupted; the switch waits for its terminal outcome.
- [ ] A version that fails to write the readiness marker is reverted automatically and never retried.
- [ ] A failed check is quiet; only a rejected token notifies.
- [ ] Covered at the service seam with fake release archives; one real tag-to-update round trip is done on both machines.
- [ ] ADR 0007 holds as written.

## Comments

- 2026-11-20 (from ticket 11): release asset contract.
  - Each `v<version>` tag on the private repo carries `midgard-farm-<version>-linux-x86_64.tar.gz` and `midgard-farm-<version>-windows-x86_64.zip`, each with a `<asset>.sha256` sidecar.
  - Each archive contains a top-level `midgard-farm/` onedir with `midgard-farm-service[.exe]` and `midgard-farm[.exe]`.
  - Prereleases (PEP 440 pre segment) are GitHub prereleases; the updater ignores them.
  - The version at runtime is `midgard_farm.assets.version()`.
  - The service's self-check is `midgard-farm-service --self-check <out.json>` (`packaging/service_entry.py`); use it, or the readiness marker, for the 60 s ready check.
  - First real release: v0.1.0 (`b91de77`).
