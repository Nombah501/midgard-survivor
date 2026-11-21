# The window owns the run choice; a preset owns only strategy

Status: accepted

The app spec had a preset carry location and difficulty and the window never edit presets, so choosing where and how hard to play meant picking or writing a preset. The operator wants to choose like in the game. The window is now the single source of the run choice: character, location (or Automatic), difficulty (or Automatic, else a fixed level in the location's range), oaths, the keep wishlist and the maintenance switches, fixed at Start or Resume and stored per machine. A preset keeps only strategy: objective, speeds, session limits and the ceiling Automatic may reach; `stage`, `danger` and `class` leave the presets.

## Considered Options

- **Window values override preset values:** rejected. Two sources for the same field make it unclear where a run's location came from.
- **Window edits and saves preset files:** rejected. Presets become per-machine state and stop being shared strategies.

## Consequences

- Oaths are passed to the game per run and only apply at difficulty 30; the profile's own oath set is never written (ADR 0008).
- Presets that differed only by location, difficulty or class (`synx-hell`, `sniper-hell`) are deleted; `one-run` moves to test data.
- Character and preset are fixed at Start for the whole session. To change
  either, finish and start a new session. Location, difficulty, oaths, wishlist
  and maintenance switches can also change while paused, for the next run.
- The window also remembers **Show game window**, default off. `display` is launch configuration, not strategy; a change on Resume takes effect only when the game next launches.
- All locations in turn is a window-owned location choice that cycles through unlocked locations in catalog order at a shared fixed or per-location Automatic difficulty, retaining its position across same-session restarts.
