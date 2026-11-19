# 07: How the app updates itself

Type: grilling
Status: resolved
Blocked by: 04

## Question

How does a new version of the app reach both machines, and how is it applied safely?

- **Source of versions.** There is no git remote today. Options: a private GitHub repo with Releases, a local folder or share, git pull on each machine.
- **Who starts it and when.** A button in the GUI, or a check on start.
- **What happens to a running AFK during the replacement.** Wait for the session to end, or finish it, update, then restart.
- **Rollback** if the new version does not start.
- **Compatibility.** A farmer patch from the old version of `farmer.gd` vs the new app: an app update may itself require rebuilding the farmer patch.
- **Unblocking a failed rebuild.** From 06: a failed Game update rebuild is blocked per (official patch sha, app version), so an App update that fixes the farmer must trigger the rebuild by itself. Decide how the new version announces that, and whether every App update rebuilds the farmer patch.
- **When to install (from 05's mock).** Automatically after the AFK session ends, or only with the operator's consent.
- **Where the Windows build runs (from 04 Q12).** On gpu-pc over SSH today. If the source of versions becomes a hosted remote, decide whether CI builds the Windows onedir instead.

## Answer

Grilled with the operator, 2026-11-19. Every recommendation accepted. Decision record: [ADR 0007](../../../docs/adr/0007-app-self-updates-versioned-user-dir.md).

**Gist:** GitHub Actions builds both onedirs from a `v*` tag into a private release. The service checks at start and daily, downloads and verifies, then switches `current` in a quiet window and reverts by itself if the new version is not ready within 60 s. The farmer is rebuilt only when the **Farmer hash** changes.


- **Q1 source of versions:** a private GitHub repo (account Nombah501) with Releases; a `vX.Y.Z` tag yields a release with Linux and Windows artifacts. Each machine holds a fine-grained read-only PAT (`contents:read`, this repo only), entered once.
- **Q2 install form (revises 04 Q3):** PyInstaller onedir on both OSes in a user-owned versioned directory: `~/.local/share/midgardfarm/versions/<v>/` and `%LOCALAPPDATA%\MidgardFarm\versions\<v>\`, with a `current` pointer. No root, no PKGBUILD.
- **Q3 when:** the service checks at start and once a day; it downloads and sha256-verifies a new version at once and installs it automatically in a quiet window (no AFK session, game not running). The window shows "version X installed" with a rollback button.
- **Q4 running AFK:** never interrupted; the new version waits for the session's terminal outcome and is installed before the next start.
- **Q5 farmer rebuild (refines 06 Q12):** only when the farmer build inputs change (`farmer.gd`, `save_hook.gd`, injectors, `FARMER_API`, bytecode). Their hash ("farmer hash") is stored in `patch_farmer.info` and compared in 06's pre-launch check; a mismatch runs 06's pipeline (build → smoke → install). 06's quarantine block is keyed by (official patch sha, farmer hash) instead of (sha, app version).
- **Q6 failed start and rollback:** after `current` switches, the new service must write a readiness marker within 60 s (config read, profile found by markers, `platform` checks passed). Without it the pointer reverts, a high-priority notification says "update to X rolled back", and that version is marked bad and never retried. A manual rollback button exists too. Kept: the current version plus one previous. A rollback that changes the farmer hash rebuilds through 06's pipeline (Q5).
- **Q7 who builds releases (replaces 04 Q12):** GitHub Actions on a `v*` tag. `ubuntu-latest` and `windows-latest` run pytest (Windows includes `platform`), build both onedirs and publish the release with sha256 files. gpu-pc carries no dev tooling; the live-game smoke still runs on each machine before installing a farmer patch (06).
- **Q8 data formats:** backward-compatible by default (new fields only, no renames or removals), so rollback is always safe. A breaking change is an explicit release exception: it adds a `schema` field, migrates forward after a backup, shows in the window, and a rollback across it restores the pre-migration backup.
- **Q9 failed update check:** quiet. The window shows "updates not checked for N days (reason)". Only a rejected token (401/403) sends one notification: "enter a new token".
