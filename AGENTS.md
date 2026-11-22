# AGENTS.md

## Agent skills

### Issue tracker

Local markdown under `.scratch/<feature>/issues/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical roles: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `GLOSSARY.md` and `docs/adr/`. See `docs/agents/domain.md`.

### Farmer code

Before changing or reviewing the farmer, supervisor, `run.sh` or `verify.sh`, read `docs/agents/farmer-map.md`: lifecycle by function name, contracts, how to verify.

### App code

Before planning or delegating a change to the window, service, updates or release, read `docs/agents/app-map.md`: which files move together, regeneration steps, the release script.

### Live farm

Asked whether the farm is running or farming: run `.venv/bin/python -m midgard_farm.health` (read-only, two samples). A fresh heartbeat in phase `run` is not progress; only the run's game time is.
