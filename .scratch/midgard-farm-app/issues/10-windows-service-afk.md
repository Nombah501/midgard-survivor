# 10: Windows: service and AFK on gpu-pc

**What to build:** The service runs on Windows as a hidden Task Scheduler task at logon (no elevation) and runs a supervised AFK session on gpu-pc. The game runs in a Job Object so the whole tree is killed, notifications are Windows toasts, and the farmer patch is built on the machine. Windows v1 runs without network isolation, as the spec records.

**Blocked by:** 03, 05.

**Status:** ready-for-human (box 4 on gpu-pc; README 'Verify on gpu-pc')

- [x] Task registration and removal work without admin rights; the task restarts on failure and survives a closed window.
- [x] Killing the session kills the game tree through the Job Object.
- [x] Toast notifications appear from the windowless service.
- [ ] On gpu-pc: the farmer patch builds byte-identically to Linux, and a supervised session of several runs finishes with a correct terminal outcome despite the missing exit code.
- [x] The missing isolation and its risks (updater prompt, CloudSave race) are documented in the README.

## Comments

- 2026-11-19 (review of ticket 03): the injectors (`farmer/tools/inject_hook.py`, `patch_player.py`) write text with the platform's default newline, so on Windows the injected `.gd` files get CRLF. Byte-identical Linux and Windows builds are therefore assumed, not yet tested, on the Python path. Check this first on gpu-pc. If the packs differ, make the injectors write `\n`; that changes the Farmer hash inputs, so rebuild on both machines.
- 2026-11-20 (from ticket 08): the window's "Start service" runs the scheduled task named `Midgard Farm` (`platform/windows.py` `SERVICE_TASK_NAME`). Register the task under exactly that name. On Linux the window runs `systemctl --user start midgard-farm.service`.
- 2026-11-20: Done in `3ed3fa9` and `17fa7d7` (review fixes). CI run 44619850522 passed on Linux and Windows; the Windows-only scheduler round trip and the Job Object crash test ran there.
  - Registration: `service.py --register` / `--unregister` / `--print-task` / `--dry-run` register a hidden least-privilege logon task with restart on failure. Unregister is idempotent.
  - Job Objects kill the game on close.
  - Game discovery reads the running `MidgardSurvivors.exe` path from a native process snapshot. `GAME_DIR` and `config.json` `game_dir` override it.
  - Injector outputs are normalised to LF before compile.
  - The toast's structure and registration are tested; its visible display is checked on gpu-pc.
  - Commit `3ed3fa9` alone fails one test, whose decoder landed in `997209d`. Since then every commit is tested from a clean export before it is pushed.
  - Independent review: CHANGES_REQUIRED; fixed.
  - Operator: run the three steps in README 'Verify on gpu-pc'.
