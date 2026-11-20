# 06: Maintenance switches in the window

**What to build:** The window offers four switches: Kafra/Sage upgrades, fusion of spare card copies, Star Smith on unworn stored items, storage cleanup. Start and Resume carry them into `farmer.cfg`; the window remembers them. The switch keys (`auto_upgrades`, `auto_sage`, `auto_fuse`, `auto_potential`, `auto_storage_prune`) leave every preset; a preset containing one is refused naming the key.

**Blocked by:** 01, 03.

**Status:** ready-for-agent

- [ ] The four switches are on the AFK screen, editable only when Start or Resume is possible, and remembered; covered by GUI tests.
- [ ] Start and Resume carry the switches; the service writes them into `farmer.cfg`; the preset never contributes them; a preset containing a switch key is refused naming the key.
- [ ] Each switchable maintenance action follows its switch; Star Smith never touches a worn item.
- [ ] Static checks and the pytest suite pass.

Spec: [`../spec.md`](../spec.md).
