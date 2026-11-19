# 09: How the window talks to the AFK service

Type: grilling
Status: open
Blocked by: 04

## Question

Today the contract between the farmer, the supervisor and anything watching is files: `farmer_status.json`, `farmer_command`, `quarantine.json`. 05 fixed what the window shows: the phase and heartbeat, the four commands, the History list with update events, the Game update states and outcomes from 06, and the quarantine cause with one next action. AFK runs as a background service, and the window is a remote control that can be closed and reopened at any time.

- Do files (polled) carry all of that on both OSes, or does the window need a live channel (a local socket or pipe) for push updates?
- Where the History lines (sessions plus update events) are written and who writes them: the supervisor, the app, or both.
- How the window learns the service is alive at all (the service is down vs. AFK is idle vs. the farmer is stalled).
- How "Check again" and Start reach a service that may be in quarantine or not running.

Depends on 04: the stack decides what a live channel would cost.

## Comments

- 2026-11-19: deferred by the operator; the spec goes ahead without it. Spec default: the window polls the existing file contract (`farmer_status.json`, `farmer_command`, `quarantine.json`) plus a history file the service appends.
