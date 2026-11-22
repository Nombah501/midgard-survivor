---
version: 1
slug: "src-midgard-farm-gui-main-qml"
primary_target: "src/midgard_farm/gui/Main.qml"
related_targets: []
---

## Scope

Whole Midgard Farm window (`src/midgard_farm/gui/Main.qml`): AFK session, History, Updates, Quarantine, abort dialog. Mode: Operate. Operator sets up and glances equally; Linux large monitor, Windows, small windows.

## Direction contract

THESIS: The night of farming is an inscription. The window owns one idea, the session's runs drawn as a painted band in rotation order, and refuses the category default of identical stat cards and a generic settings form.

OWN-WORLD: Dark granite ground #1c1e1d, raised stone #2b2e2c, hairline #3a3e3b, painted white #e8e2d3, muted bone #a9a597, red ochre #b6432a (live state and primary action), yellow ochre #c9943c (earnings, wins). Noto Sans bundled, regular and bold; 2px corners; frames only around things you press.

STORY: One look says whether the farm runs, which run it is in and what the night earned; setup reads like the game's run choice; destructive actions confirm the loss.

FIRST VIEWPORT: Top bar with name, tabs, meta. Status row: phase dot and heartbeat, "Run N · Location" large left, zeny tonight in large ochre numerals right. The run band full width beneath. Two columns: Run choice left, Session so far right. Action bar pinned at the bottom: last event left, Pause/Start, Finish after this run, Abort right.

FORM: Native Qt Quick Controls (Fusion) restyled in the palette; standard tabs, combo boxes, switches, buttons. seed: seed:683f9d97573274be.

SIGNATURE: Run band. One segment per settled run plus the current one; state by form: filled ochre win, outline loss, dashed current, struck aborted; legend top right, location ticks under the band. Reused in History per session.

## Unresolved

Band density above about 60 runs (wrap to a second row versus compress).
