# 06: Smoke run in Python

**What to build:** The app can prove a farmer patch with one sandboxed run: copy the profile into a sandbox, install the pack there, play the one-run preset and judge it. This is the smoke of the Game update pipeline and the Python form of `verify --one-run`.

**Blocked by:** 02, 03.

**Status:** ready-for-agent

- [ ] The sandbox never touches the real profile; big packs are linked, not copied.
- [ ] A 300 s hard limit applies, with one retry; the second failure is final.
- [ ] Pass requires status done and not failed, at least one win with the last run a victory, kills > 0, zeny gain > 0, a FINISH marker and no script errors in the game output.
- [ ] Game output is captured from the process directly (Windows does not provide `godot.log`).
- [ ] It refuses while the game runs.
