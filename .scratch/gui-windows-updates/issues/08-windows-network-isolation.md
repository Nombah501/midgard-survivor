# 08: Network isolation on Windows

Type: grilling
Status: open
Blocked by: 03

## Question

How (and whether) to cut the game's network during AFK on Windows, given 01's facts?

- Per-exe Windows Firewall rules need admin rights and survive a crash. WFP dynamic filters vanish with their session but need a privileged process. Windows Sandbox has no network but is a different environment.
- Why isolation exists: cloud sync must not race the farm (ADR 0002), and the official patch prompt must not appear during AFK. Since profiles are independent and not synced (Q7), is the first reason still alive on Windows? Is the second covered by the game's offline mode or a timeout?
- Options: a one-time elevated setup that creates the rules, with the app only toggling them; a dynamic filter from a privileged helper; no isolation on Windows (a conscious divergence from ADR 0002).

Depends on 03: whether this Windows account has admin rights.

## Comments

- 2026-11-19: deferred by the operator; the spec goes ahead without it. Spec default: Windows v1 runs the game without network isolation (a conscious divergence from ADR 0002); the risks are the updater's modal prompt and the CloudSave race.- Findings so far (from `cloud_save.gd`, `updater.gd`): CloudSave runs only when the profile is linked (`cloud_secret`). It syncs at game start, every 240 s outside a run and 5 s after a run, and pulls a newer cloud revision over a clean local profile, then restarts the game; a two-sided change opens a modal conflict dialog. The Linux profile is linked (`cloud_backups/`). The farmer never reads `farmer.cfg` `offline`, so ADR 0002's remark about it is stale. Whether gpu-pc uses the same cloud account is unknown (F1). Mechanism draft: a farm copy of the exe (hard-linked `.pck`) blocked by one permanent firewall rule created at elevated setup.
