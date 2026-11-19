# One Python + PySide6 package for Linux and Windows

Status: accepted

The farmer application must behave the same on Linux and Windows and be maintained by one person. The core (supervisor, patch build/install, verify) and the GUI become one Python 3.13 package with PySide6/QML. The bash scripts and the C++/QML `gui/` are deleted once the existing pytest scenarios pass against the new modules. Everything OS-specific sits behind one `platform` module.

## Considered Options

- **Go or Rust core (one static exe):** rejected. Bash had to be rewritten for Windows anyway, but these would also force a rewrite of the Python supervisor and its tests.
- **Keep C++/QML for the GUI:** rejected. It adds a second language and an MSVC build on Windows.
- **Web UI served by the service, or Tauri/Electron:** rejected. It adds a third stack.

## Consequences

- Both OSes ship as a PyInstaller onedir (ADR 0007), and Python is not required on either machine. PyInstaller cannot cross-build, so the Windows build runs on a Windows CI runner.
- Dependencies are the standard library plus PySide6. Windows mechanisms (Job Objects, file locks, scheduled tasks, toasts) go through `ctypes` and system tools.
