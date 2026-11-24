# A fixed Mode replaces presets; the karma Route is a run choice

Status: accepted (supersedes the preset half of ADR 0009)

ADR 0009 moved location, difficulty and oaths into the window and left presets as named strategies. In practice the six presets (`crumbs`, `hell-rotation`, `night`, `progress`, `steady`, `zeny`) differed mostly by run length; their objective and weights only steer Automatic location and difficulty, which an explicit choice bypasses. The karma route (Valhalla or Hel) was hidden inside `hell-rotation`. The operator wants to pick everything that shapes a run in the window and keep character preparation entirely his own job (ADR 0008).

The window now chooses a **Mode**: *Endless until the final boss* or *Short runs (until the MVP)*. Each mode is one built-in strategy file in `farmer/modes/`; there are no other presets. The window also chooses a **Route** for the karma portal after each regular MVP: *Valhalla*, *Hel* or *Random each run*. Route applies only to Endless outside the Towers. On the dark side the farmer also takes Hel altars.

## Considered Options

- **Keep presets with human names:** rejected. Users still had to know which file implied which route and run length.
- **Expose every strategy knob in the window:** rejected. Objective weights, ceilings and speeds are tuning, not run choices.

## Consequences

- `Start` no longer carries a preset path; the supervisor resolves `farmer/modes/<mode>.json`. The service CLI still accepts an explicit strategy JSON for development and soaks.
- Mode and Route are fixed at Start like location and can change while paused for the next run. Character stays fixed for the session.
- A saved window choice from 0.4.x with a `preset` key loads as Endless with Valhalla.
- `karma_route: "natural"` remains a farmer value for test scenarios only; the window never offers it.
