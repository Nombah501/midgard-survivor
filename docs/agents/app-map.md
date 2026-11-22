# App code map

Where the Python service and window live (`src/midgard_farm/`). The farmer itself is in `docs/agents/farmer-map.md`. Use this to claim the whole file set of a change up front: most window features cross four or five files.

## Change → files

| Change | Files that move together |
|---|---|
| New window control or command | `gui/Main.qml` → `gui/window.py` (Qt slot, worker) → `gui/model.py` (`SessionModel`, views) → `core/commands.py` (command, `SessionSettings`) → `core/supervisor.py` (consumer, refusals). Regenerate `gui/_resources.py`. |
| Something the farmer child must know at boot | `core/supervisor.py` → `core/launch.py` (child env/config) → `farmer/src/farmer.gd`. Fakes: `tests/fake_supervised_game.py`. |
| Data shown from the farmer | `farmer/src/farmer.gd` (catalog/status/journal) → `core/catalog.py` or `core/history.py` → `gui/model.py`. |
| Session history fields | `core/supervisor.py` (writer) → `core/history.py` (reader, Night) → `gui/model.py`. Keep old rows loadable. |
| Game patch build, install, repair | `core/game_update.py`, `core/farmer_patch/{build,install,gdre}.py`, `core/preflight.py`, `core/smoke.py`; idle-path trigger in `core/supervisor.py`. |
| App updates | `core/_app_releases.py` (signed channel client), `core/app_update.py` (check, stage, handoff, status for the window), `service.py`, `packaging/publish_update.py`, release job in `.github/workflows/ci.yml`; contract in `docs/adr/0010-signed-app-update-channel.md`. |
| Diagnostics | `core/doctor.py` (checks, `repair_farmer_pack`), CLI `doctor.py`, Health tab in `gui/`. Read-only OS queries go through `platform/{__init__,linux,windows}.py`. |
| OS behaviour | `platform/linux.py`, `platform/windows.py`, `platform/_systemd.py`; type-check both with mypy `--platform linux` and `--platform win32`. |
| Real-game scenario | `verify/scenarios.py`, `verify/judges.py`, `verify/drive.py`; fake game `tests/fake_verify_game.py`; registry test `tests/test_verify.py`. |

## Gotchas

- After any `gui/*.qml` or `window.qrc` change run `.venv/bin/pyside6-rcc --format-version 1 --compress-algo zlib -o src/midgard_farm/gui/_resources.py src/midgard_farm/gui/window.qrc`; tests compare the bundle byte for byte, and every bundled text file needs `text eol=lf` in `.gitattributes`.
- GUI tests: wait for the published state (`wait_until`, the readiness helper in `tests/test_gui.py`) before asserting enablement or layout; CI runners are slow.
- Doctor checks and other slow reads run on their own worker in `gui/window.py`, never on the poll/command worker.
- Release with `packaging/release.sh X.Y.Z`: it tags only after master CI is green on both OSes and ends by fetching the stable channel as an App does (`packaging/check_published.py`).
