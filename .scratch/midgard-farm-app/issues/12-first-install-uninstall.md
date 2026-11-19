# 12: First install and uninstall

**What to build:** The operator downloads a release archive once, unpacks it and runs setup. Setup copies itself into the versioned user directory, sets `current`, asks for the read-only token, registers the service and, on Windows, warns if auto-logon is off or Windows Update active hours do not cover the night. Uninstall removes the service and restores the official patch while keeping the profile, logs and history.

**Blocked by:** 10, 11.

**Status:** ready-for-agent

- [ ] Setup needs no root on Linux and no admin on Windows.
- [ ] The token is stored in the app's data, never in the repo or logs.
- [ ] The Windows warnings only read settings; they change nothing.
- [ ] Uninstall leaves the game launching unmodified, verified on both machines.
