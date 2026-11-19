# Windows

Run from a checkout with Python 3.13. No app installer, bash, or administrator rights are needed. In an **unelevated** PowerShell at the checkout root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install 'PySide6>=6.8'
Set-Location src
..\.venv\Scripts\python.exe -m midgard_farm.service --print-task
..\.venv\Scripts\python.exe -m midgard_farm.service --register
schtasks.exe /Run /TN 'Midgard Farm'
..\.venv\Scripts\python.exe -c 'from midgard_farm.gui import main; raise SystemExit(main())'
```

`--print-task` (or `--register --dry-run`) only renders the task. Registration uses the current user's interactive session and runs the service at logon without a console. The task retries a failure up to three times, one minute apart. You can close the app window or lock the screen; stay signed in and keep the machine awake. If you move the checkout or its virtual environment, register again. To remove the registration, finish any AFK session, stop the task with `schtasks.exe /End /TN 'Midgard Farm'` if it is running, then run `..\.venv\Scripts\python.exe -m midgard_farm.service --unregister` from `src`.

With the service running, start `MidgardSurvivors.exe` manually once, accept any official update, then close the game. The service remembers its location. `GAME_DIR` (when set in the service's environment) overrides the absolute `game_dir` in `%LOCALAPPDATA%\MidgardFarm\config.json`; both override the remembered location. For example: `{"game_dir": "C:\\Games\\Midgard Survivors"}`. Once the service is ready, select a character and preset in the window and start an AFK session.

**Windows v1 does not isolate the game from the network.** An official updater prompt can stall an unattended session. On a CloudSave-linked profile, a cloud pull can restart the game or a conflict dialog can block it. The Linux profile is CloudSave-linked; check whether gpu-pc uses the same cloud account before farming on both machines. Do not run simultaneous farms against the same cloud profile.
