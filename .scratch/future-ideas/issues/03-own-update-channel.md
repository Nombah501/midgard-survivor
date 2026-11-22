# 03: Own update channel with "Check for updates" and changelog

**Status:** needs-triage (needs grilling)

**Idea (Operator, 2026-11-22):** rethink App updates. No GitHub token, no dependence on a public repo. The App has its own update channel, a **Check for updates** button, a changelog for the new version, and a more human update flow overall.

**Today (v0.3.9):** `src/midgard_farm/core/_app_releases.py` reads `api.github.com/repos/Nombah501/midgard-survivor/releases` with a Bearer token and downloads assets; `app_update.py` checks every `CHECK_INTERVAL = 86400` s and hands off to the supervisor/watchdog. Linux live service is switched by hand (git checkout of a tag). Trust today rests on GitHub HTTPS + token + `.sha256` assets.

**Questions for grilling:**
- Where the channel lives: own server/VPS, object storage (S3/R2) with a static manifest, something else. Who pays/hosts; availability when the Operator's PC is off.
- Trust without GitHub auth: a signed manifest (e.g. Ed25519/minisign; public key baked into the App) covering version, archive SHA-256, changelog. Downgrade/rollback protection.
- Publishing: CI uploads to the channel after the release job; private repo again?
- UX: button in the window, "what's new" text from the changelog, update now / later, progress, failure message; keep the existing verified handoff and rollback (`bad` versions).
- Linux: does the live service also update itself through this channel instead of `git checkout`?
- Changelog source: a `CHANGELOG.md` maintained per release (none exists yet) vs. commit subjects.
