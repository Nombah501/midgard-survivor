# 14: Remaining verify scenarios and soak in Python

**What to build:** Every other scenario of `verify.sh` (supervised runs, operator commands, fault injection) and the soak check are ported to Python on top of the smoke run. The soak stays Linux-only.

**Blocked by:** 04, 06.

**Status:** ready-for-agent

- [ ] Each `verify.sh` scenario has a Python equivalent with the same assertions.
- [ ] The soak check runs on Linux and produces the same verdicts as today.
- [ ] Live-game scenarios stay out of CI.
