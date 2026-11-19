# 01: Repo, package skeleton, platform seam and CI

**What to build:** A private GitHub repository holds the project, and the new Python package exists with a service entry point. The platform seam has a Linux and a Windows implementation for the single-instance lock, locating the profile by markers, atomic file replace and killing a process tree. CI runs the tests on Linux and Windows on every push. Nothing changes for the running Linux farm.

**Blocked by:** None (can start immediately).

**Status:** resolved

- [x] A private repo under the operator's GitHub account exists; the existing history is pushed and `origin` is set.
- [x] The package installs in development mode on Python 3.13 and depends only on the standard library and PySide6.
- [x] The platform interface is one module with Linux and Windows implementations; the core never branches on the OS itself.
- [x] Profile discovery finds the profile by `profile.json` + `patches/state.json` under the Godot user-data root, including a folder name with a space; tested on both OSes.
- [x] Lock exclusivity, tree kill (including grandchildren) and atomic replace are tested against the real OS on both CI runners.
- [x] CI is green on `ubuntu-latest` and `windows-latest`; the existing farmer pytest suites also run in CI on Linux.

## Comments

- 2026-11-19: Done in `a8bf71a` and `f035830`. Repo: `Nombah501/midgard-survivor` (private). Package `midgard_farm` under `src/`; interface `midgard_farm/platform/__init__.py` (`Platform`, `InstanceLock`, `ProcessTree`), implementations `linux.py` (flock, process group, `os.replace` + dir fsync) and `windows.py` (LockFileEx, suspended start into a Job Object, MoveFileExW with retry on sharing violations). `core/profile.find_profile` refuses ambiguity (two marked folders). Entry point `midgard-farm-service`: takes the service lock, finds the profile, exits 0 / 75 (already running) / 78 (no profile). CI run 44579502756 green on both runners; on ubuntu-latest 11 `run.sh` isolation tests skip because the runner cannot create a user+network namespace (`unshare -cn`), so they still run only locally.
