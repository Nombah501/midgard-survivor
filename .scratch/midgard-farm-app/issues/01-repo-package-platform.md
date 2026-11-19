# 01: Repo, package skeleton, platform seam and CI

**What to build:** A private GitHub repository holds the project, and the new Python package exists with a service entry point. The platform seam has a Linux and a Windows implementation for the single-instance lock, locating the profile by markers, atomic file replace and killing a process tree. CI runs the tests on Linux and Windows on every push. Nothing changes for the running Linux farm.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] A private repo under the operator's GitHub account exists; the existing history is pushed and `origin` is set.
- [ ] The package installs in development mode on Python 3.13 and depends only on the standard library and PySide6.
- [ ] The platform interface is one module with Linux and Windows implementations; the core never branches on the OS itself.
- [ ] Profile discovery finds the profile by `profile.json` + `patches/state.json` under the Godot user-data root, including a folder name with a space; tested on both OSes.
- [ ] Lock exclusivity, tree kill (including grandchildren) and atomic replace are tested against the real OS on both CI runners.
- [ ] CI is green on `ubuntu-latest` and `windows-latest`; the existing farmer pytest suites also run in CI on Linux.
