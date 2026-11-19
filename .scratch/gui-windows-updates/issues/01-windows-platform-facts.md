# 01: Windows platform facts for the farmer

Type: research
Status: resolved
Blocked by: none

## Question

What does Windows offer for each Linux mechanism the farmer relies on? The inventory is in `docs/agents/farmer-map.md` and the Linux-only list from charting.

- **GDRE Tools v2.7.4 on Windows.** Is there a CLI build with the same commands as `build.sh` (`--headless --extract/--decompile/--compile/--pck-patch/--list-files`, bytecode `ebc36a7`)? Is it headless, with no console window?
- **Godot 4 headless on Windows.** What exit code does `OS.kill(OS.get_process_id())` give (`hard_exit`)? Is `DirAccess.rename_absolute` atomic when it replaces an existing file (status and checkpoint)?
- **Where the game keeps its data.** Default `user://` for a Godot app without `use_custom_user_dir` (expected: `%APPDATA%\Godot\app_userdata\Midgard Survivors`).
- **Single instance.** File lock plus a check for the game process without `/proc` and `pgrep`.
- **Per-exe network isolation** (a replacement for `unshare -cn`). Windows Firewall rules for one program: are admin rights needed, and how to enable and disable them per session? Alternatives.
- **Background AFK service with the window closed.** Task Scheduler (at logon / on demand), a Windows service, a tray process. Which of them survives closing the window, logout and sleep? Can each run a GUI-less game process in the user session? Rights.
- **Notifications.** Toast notifications from a background process with no window.
- **Process group.** An equivalent of `killpg` / `start_new_session` (Job Objects) so the supervisor can kill the whole game process tree.

Answer: facts with links to primary sources; mark guesses [INFERENCE].

## Answer

1. **GDRE Tools v2.7.4:** The [Windows ZIP](https://github.com/GDRETools/gdsdecomp/releases/tag/v2.7.4) contains GUI-subsystem `gdre_tools.exe` and no console wrapper (verified from the ZIP and PE header). Use `--headless` for the [same CLI commands](https://github.com/GDRETools/gdsdecomp/blob/v2.7.4/README.md#L44-L69), including extract, decompile, compile, PCK patch and list files, with [`--bytecode=ebc36a7`](https://github.com/GDRETools/gdsdecomp/blob/v2.7.4/bytecode/bytecode_ebc36a7.h#L10-L23) for compile/decompile. This launches without allocating a console; an existing parent console can still be used.
2. **Godot headless:** Windows self-kill calls [`TerminateProcess(handle, 0)`](https://github.com/godotengine/godot/blob/4.5-stable/platform/windows/os_windows.cpp#L1511-L1532): the exit code is **0**, not `-9`, for success or failure using this path. Keep the matching terminal status authoritative. [Windows `DirAccess.rename_absolute`](https://github.com/godotengine/godot/blob/4.5-stable/drivers/windows/dir_access_windows.cpp#L302-L327) deletes the existing file before moving the temp file: **not atomic**. Status and checkpoint need a true single-operation replacement.
3. **Data path:** Godot defaults to [`%APPDATA%\Godot\app_userdata\[effective project name]`](https://docs.godotengine.org/en/4.5/tutorials/io/data_paths.html#accessing-persistent-user-data-user) under the game account. [INFERENCE] `Midgard Survivors` is a candidate, not a verified Windows folder: local recovered `analysis/proj/project.godot` says `Ragnarok Survivors`. Verify the effective settings of the exact Windows package before choosing a profile.
4. **Single instance:** Hold a per-profile [`LockFileEx`](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex) lock over the child lifetime, and use [Toolhelp PID enumeration](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot) plus [`QueryFullProcessImageNameW`](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew) for the stock game. The snapshot cannot prevent a non-cooperating manual launch after preflight.
5. **Network isolation:** Use [elevated](https://learn.microsoft.com/en-us/troubleshoot/windows-server/networking/netsh-advfirewall-firewall-control-firewall-behavior) inbound/outbound [`-Program` block rules](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule) for the absolute game EXE. Enable and verify effective policy before starting; disable/remove after the tree exits. Rules apply to all instances at that path and persist after a crash. Alternatives: [privileged dynamic WFP filters](https://learn.microsoft.com/en-us/windows/win32/api/fwpmtypes/ns-fwpmtypes-fwpm_session0) or a [separate network-disabled Sandbox guest](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file#networking).
6. **Background lifetime:** An independent [interactive scheduled task](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks) (logon/on demand) or tray agent can launch headless in the user's session without elevation and survive closing the front end, but not sign-out. A password/S4U task can run signed out in a separate noninteractive context with batch-logon rights; a [service](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services) survives sign-out in Session 0, needs admin to install by default, and cannot directly inherit the interactive session. [No option farms through real sleep](https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/integrating-apps-with-modern-standby).
7. **Notifications:** [Register and show Windows App SDK notifications](https://learn.microsoft.com/en-us/windows/apps/develop/notifications/app-notifications/app-notifications-dotnet) from an unelevated user-session process; no visible window is needed. [INFERENCE] Use an interactive helper for a service or noninteractive task, not direct service toasts.
8. **Process tree:** Use a [Job Object](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) with kill-on-last-handle-close and no breakaway, assign before the game runs, and force-stop with `TerminateJobObject`. Ordinary child processes inherit membership; another broker's processes may not.

Findings: branch `research/windows-platform-facts`, file `research/windows-platform-facts.md` in worktree `../midgard-research-windows-platform-facts` (commit `62f0579883`).
