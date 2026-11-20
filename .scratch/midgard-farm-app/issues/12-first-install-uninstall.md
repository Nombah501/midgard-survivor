# 12: First install and uninstall

**What to build:** The operator downloads a release archive once, unpacks it and runs setup. Setup copies itself into the versioned user directory, sets `current`, asks for the read-only token, registers the service and, on Windows, warns if auto-logon is off or Windows Update active hours do not cover the night. Uninstall removes the service and restores the official patch while keeping the profile, logs and history.

**Blocked by:** 10, 11.

**Status:** ready-for-human (verify on both machines that uninstall leaves the game launching unmodified)

- [x] Setup needs no root on Linux and no admin on Windows.
- [x] The token is stored in the app's data, never in the repo or logs.
- [x] The Windows warnings only read settings; they change nothing.
- [ ] Uninstall leaves the game launching unmodified, verified on both machines.

## Comments

- 2026-11-20: The release ships `midgard-farm-setup[.exe]`, which copies the onedir to `versions/<version>/`, writes `current` atomically, prompts without echo for a read-only release token and stores it in `<app-data>/release-token` (0600 on Linux). Setup registers the systemd user unit or hidden least-privilege Windows logon task. Both start the stable `bin/midgard-farm-launcher[.exe]`, which reads `current` on every start. Only rerunning setup refreshes the launcher. Windows setup reads the auto-logon and Windows Update active hours settings without changing them.
- 2026-11-20: `--uninstall` stops and removes the service registration, restores the official state through the existing `patches/official-state.json` restore path and keeps the profile, logs and history. Fixture tests exercise install, rerun, pointer switches and bad pointers, token storage, and uninstall. The operator still needs to verify on both machines that the game launches unmodified after uninstall; see the README for the commands and legacy cutover prerequisite.
- 2026-11-20 (review fixes): Setup repairs incomplete version directories before selecting them, and `--print-registration` lets the archive smoke check verify the stable launcher target. Uninstall finds a profile with an official snapshot even if its current state file is missing, and holds both legacy locks while restoring it.
