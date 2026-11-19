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

## Verify on gpu-pc

1. **Compare builds.** On both machines, use the same checkout revision and a copied profile with the same official patch and bridge. If a farmer patch is mounted, the copy must also have its `patches/official-state.json`. Use matching base packs if extraction falls back to the base. Never run this against the live Linux profile. Save the following as `parity.py` in the checkout's `src` directory on each machine. From `src`, run it with the checkout's Python 3.13 and the arguments `parity.py "<copied profile>" "<game directory>"`:

   ```python
   import os
   import sys
   import tempfile
   from pathlib import Path
   from midgard_farm.core.farmer_patch import build
   from midgard_farm.platform import current

   profile, game_dir = map(Path, sys.argv[1:])
   os.environ["GAME_DIR"] = str(game_dir.resolve())
   with tempfile.TemporaryDirectory() as data:
       os.environ["LOCALAPPDATA" if sys.platform == "win32" else "XDG_DATA_HOME"] = data
       result = build(current(), profile.resolve())
       for name in ("patch_sha256", "bridge_sha256", "farmer_hash", "result_sha256"):
           print(name, getattr(result, name))
   ```

   All four hashes must match. This only builds; it does not install a patch.

2. **Verify discovery.** In a normal unelevated Windows session with no `GAME_DIR` or `game_dir` override, register and start `Midgard Farm` as above. Start the game once on gpu-pc, accept any official update, and close it. In PowerShell, `Get-Content "$env:LOCALAPPDATA\MidgardFarm\game-executable.txt"` must show the correct absolute exe path.

3. **Run three supervised runs.** Use an unlinked or independent gpu-pc profile. When the service is ready, run this from `src` in PowerShell:

   ```powershell
   @'
   import json, tempfile
   from pathlib import Path
   from midgard_farm.core.commands import Start, submit
   from midgard_farm.platform import current

   preset = json.loads(Path("../farmer/presets/one-run.json").read_text(encoding="utf-8"))
   preset["max_runs"] = 3
   path = Path(tempfile.mkdtemp()) / "three-runs.json"
   path.write_text(json.dumps(preset), encoding="utf-8")
   print(submit(current(), Start(None, path)))
   '@ | ..\.venv\Scripts\python.exe -
   ```

   Close the window after the first run starts. Under `%LOCALAPPDATA%\MidgardFarm`, the newest `logs\supervisor-*\outcome.json` must report `kind: finished`, `reason: max_runs`, and `totals.runs: 3`. Check the matching entry in `history.jsonl`, a completion toast, and that `Get-Process MidgardSurvivors -ErrorAction SilentlyContinue` returns nothing. The matching farmer terminal status, not the Windows game exit code, proves the finish.
