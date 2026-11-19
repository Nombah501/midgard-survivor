# 04: Application stack

Type: grilling
Status: resolved
Blocked by: 01, 03

## Question

What is the application built on, so that it behaves the same on Linux and Windows and one person can maintain it?

- **Core** (supervisor, preflight, build/install, verify, soak). Today it is Python plus bash. Move everything to Python, or something else?
- **GUI toolkit.** Keep Qt but via PySide6, so there is one language with the core? Keep C++/QML? A web shell (Tauri/Electron)? Anything else?
- **Packaging per OS.** Windows: installer, embedded Python or a frozen exe. Linux: the current PKGBUILD, AppImage, or something else.
- **The background service mechanism on each OS**, which comes from 01.

This decides the fate of the current `gui/` and the bash tools (fog on the map).

## Answer

Grilled with the operator, 2026-11-19. Every recommendation accepted. Decision record: [ADR 0006](../../../docs/adr/0006-python-pyside6-one-package.md).

**Gist:** Python 3.13 + PySide6/QML in one package `midgardfarm` (`core` / `platform` / `gui`), with the window and the service as two entry points. Linux: PKGBUILD + systemd user unit. Windows: PyInstaller onedir in `%LOCALAPPDATA%` + a Task Scheduler logon task. Bash and the C++ `gui/` are deleted after parity.


- **Q1 core:** everything in Python; the bash scripts become Python modules (bash does not exist on Windows; the supervisor and tests are already Python).
- **Q2 GUI:** PySide6 + QML; reuse the `.qml` files from `gui/`, rewrite `backend.cpp` in Python. Omarchy/Hyprland theming stays a Linux-only nicety; Windows gets the stock Qt style.
- **Q3 packaging** *(Linux part superseded by 07 Q2: PyInstaller onedir in a versioned user dir on both OSes, no PKGBUILD)*: Linux: PKGBUILD on pacman `python` + `pyside6`. Windows: PyInstaller onedir, unpacked into `%LOCALAPPDATA%\MidgardFarm`, the app registers its own service; no installer, no system Python. Delivery of new versions is 07.
- **Q4 background service:** Linux: systemd user unit (as today). Windows: a Task Scheduler task at user logon, hidden, restart on failure. Not a Windows service (session 0 cannot run the game in the user session).
- **Q5 overnight on Windows:** the operator stays signed in; the app checks auto-logon and Windows Update active hours at setup and warns if missing, but changes nothing itself.
- **Q6 current `gui/`:** deleted with `bin/` and its PKGBUILD at cutover. The screens are built from 05's mock; only components (`StatCard`, `LogPanel`) are lifted from the old QML. Two windows never coexist.
- **Q7 layout:** one Python package `midgardfarm/` with `core/` (supervisor, build/install, verify, the Game update states from 06), `platform/` (Linux, Windows) and `gui/`; two entry points, the window and the service. `farmer/src/*.gd` stays a build input. One app version, which keys 06's (official patch sha, app version) block.
- **Q8 GDRE:** downloaded on first build, sha256-verified against a pinned value, kept in the app data dir. The build always runs before the game starts, when the network is available.
- **Q9 dependencies:** stdlib + PySide6 only. Platform specifics go through `ctypes`, `subprocess`, `schtasks`/PowerShell; ntfy through `urllib`. Any exception is argued one by one in the spec.
- **Q10 cutover:** port everything, `verify.sh` included, then delete bash once the existing pytest scenarios (`test_run_sh.py`, `test_supervisor.py`, `test_soak_check.py`) pass against the new modules. No Python→bash shims. The Linux farm keeps running on the old code until then. `verify --one-run` becomes 06's smoke on both OSes.
- **Q11 OS seam:** one `platform` module with a Linux and a Windows implementation for: single-instance lock, finding the game process, killing the process tree (`killpg` / Job Object), service registration, notifications, locating the profile by markers (03) and network isolation (08). The rest of the core is shared. Process arguments are always passed as a list (03's quoting pitfall).
- **Q12 Windows build** *(superseded by 07 Q7: GitHub Actions `windows-latest` builds and tests; gpu-pc carries no dev tooling)*: on gpu-pc over SSH, with a dev-only Python 3.13 from `uv` (not installed system-wide), building the PyInstaller onedir. Windows pytest runs for `platform` happen there too. Ticket 07 may move this to CI if it picks a hosted remote.
