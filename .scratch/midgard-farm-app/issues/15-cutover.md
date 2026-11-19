# 15: Cutover: delete bash, the C++ window and the old unit

**What to build:** With parity proven, the old path is removed in one clean cutover: the bash scripts, the old supervisor entry, the C++/QML window with its build scripts and pacman package, and the old systemd unit. The README describes the new app.

**Blocked by:** 09, 13, 14.

**Status:** ready-for-agent

- [ ] No bash script, C++ source or old unit remains; nothing calls them.
- [ ] Both machines run the released app; a night completes on each after cutover.
- [ ] The README documents install, the four screens, the Windows isolation gap and the CloudSave caveat; stale ADR remarks (ADR 0002 `offline`) are corrected.
