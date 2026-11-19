# 15: Cutover: delete bash, the C++ window and the old unit

**What to build:** With parity proven, the old path is removed in one clean cutover: the bash scripts, the old supervisor entry, the C++/QML window with its build scripts and pacman package, and the old systemd unit. The README describes the new app.

**Blocked by:** 09, 13, 14.

**Status:** ready-for-agent

- [ ] No bash script, C++ source or old unit remains; nothing calls them.
- [ ] Both machines run the released app; a night completes on each after cutover.
- [ ] The README documents install, the four screens, the Windows isolation gap and the CloudSave caveat; stale ADR remarks (ADR 0002 `offline`) are corrected.

## Comments

- 2026-11-19 (from ticket 03): the Python app keeps the official state snapshot per profile at `patches/official-state.json`. A profile still mounted on the legacy `patch_farmer.pck` has none, and the app does not guess the official file name or read the old `farmer/backups/official-state.json`. Before the first Python service start, restore the official patch with the old path (`uninstall.sh`), or seed a validated `patches/official-state.json`.
