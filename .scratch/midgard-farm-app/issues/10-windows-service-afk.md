# 10: Windows: service and AFK on gpu-pc

**What to build:** The service runs on Windows as a hidden Task Scheduler task at logon (no elevation) and runs a supervised AFK session on gpu-pc. The game runs in a Job Object so the whole tree is killed, notifications are Windows toasts, and the farmer patch is built on the machine. Windows v1 runs without network isolation, as the spec records.

**Blocked by:** 03, 05.

**Status:** ready-for-agent

- [ ] Task registration and removal work without admin rights; the task restarts on failure and survives a closed window.
- [ ] Killing the session kills the game tree through the Job Object.
- [ ] Toast notifications appear from the windowless service.
- [ ] On gpu-pc: the farmer patch builds byte-identically to Linux, and a supervised session of several runs finishes with a correct terminal outcome despite the missing exit code.
- [ ] The missing isolation and its risks (updater prompt, CloudSave race) are documented in the README.

## Comments

- 2026-11-19 (review of ticket 03): the injectors (`farmer/tools/inject_hook.py`, `patch_player.py`) write text with the platform's default newline, so on Windows the injected `.gd` files get CRLF. Byte-identical Linux and Windows builds are therefore assumed, not yet tested, on the Python path. Check this first on gpu-pc. If the packs differ, make the injectors write `\n`; that changes the Farmer hash inputs, so rebuild on both machines.
