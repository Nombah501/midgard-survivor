#Requires -Version 5.1
# Ticket 03 step 7: build the farmer patch with GDRE on Windows, run one offline
# farmer run, then restore the official state. Writes 03-windows-step7-*.json
# next to this script. The official state and profile are always restored
# (in finally), unless -KeepProfile keeps the run's profile changes.
[CmdletBinding()]
param(
    [string]$GameDir = 'C:\Users\User\Downloads\midgard-survivors-midgard-survivors-windows',
    [string]$DataDir = (Join-Path $env:APPDATA 'Godot\app_userdata\Ragnarok Survivors'),
    [int]$RunTimeoutSec = 300,
    [switch]$KeepProfile
)
$ErrorActionPreference = 'Stop'
$Kit = $PSScriptRoot
$Expected = Get-Content -LiteralPath (Join-Path $Kit 'expected.json') -Raw | ConvertFrom-Json
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Out = Join-Path $Kit "out-$Stamp"
$Work = Join-Path $Out 'work'
New-Item -ItemType Directory -Force -Path $Work | Out-Null
$Exe = Join-Path $GameDir 'MidgardSurvivors.exe'
$Patches = Join-Path $DataDir 'patches'
$State = Join-Path $Patches 'state.json'
$Utf8 = New-Object System.Text.UTF8Encoding($false)

$report = [ordered]@{ Stamp = $Stamp; Steps = @(); Facts = [ordered]@{} }
function Add-Step([string]$Name, [bool]$Ok, [string]$Detail) {
    $script:report.Steps += [ordered]@{ Step = $Name; Ok = $Ok; Detail = $Detail }
    $mark = if ($Ok) { 'OK  ' } else { 'FAIL' }
    Write-Host "[$mark] $Name  $Detail"
}
function Sha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Sha-Text([string]$Path) {
    # Line-ending-insensitive hash, in case GDRE writes CRLF on Windows.
    $t = [IO.File]::ReadAllText($Path).Replace("`r`n", "`n")
    $b = $Utf8.GetBytes($t)
    -join ([Security.Cryptography.SHA256]::Create().ComputeHash($b) | ForEach-Object { $_.ToString('x2') })
}
function Tail([string]$Path, [int]$N) {
    if (Test-Path -LiteralPath $Path) { @(Get-Content -LiteralPath $Path -Tail $N) -join "`n" } else { '' }
}
function Run-Gdre([string[]]$GdreArgs, [string]$Name) {
    # gdre_tools.exe is a GUI-subsystem exe: Start-Process -Wait is the only way to wait for it.
    # Windows PowerShell joins -ArgumentList with bare spaces, so a path like "...\Ragnarok Survivors\..." splits; quote each arg.
    $quoted = @('--headless') + $GdreArgs | ForEach-Object { '"{0}"' -f $_ }
    $p = Start-Process -FilePath $script:Gdre -ArgumentList $quoted -Wait -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Work "$Name.out.txt") -RedirectStandardError (Join-Path $Work "$Name.err.txt")
    return $p.ExitCode
}
function Game-Running { @(Get-Process -Name 'MidgardSurvivors' -ErrorAction SilentlyContinue).Count -gt 0 }
function Stop-Game { Get-Process -Name 'MidgardSurvivors' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue }

$installed = $false
$backup = Join-Path $Out 'backup'
$preexisting = @()
try {
    # --- A. Preflight -------------------------------------------------------
    if (-not (Test-Path -LiteralPath $Exe)) { throw "game exe not found: $Exe (pass -GameDir)" }
    if (-not (Test-Path -LiteralPath $State)) { throw "no state.json at $State (pass -DataDir)" }
    if (Game-Running) { throw 'the game is running; close it first' }
    $stateObj = Get-Content -LiteralPath $State -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($stateObj.file -ne $Expected.PatchFile) { throw "state.json mounts '$($stateObj.file)', expected official '$($Expected.PatchFile)'" }
    $patchPck = Join-Path $Patches $Expected.PatchFile
    $bridgePck = Join-Path $Patches $Expected.BridgeFile
    $basePck = Join-Path $GameDir 'MidgardSurvivors.pck'
    $report.Facts.StateBefore = [IO.File]::ReadAllText($State)
    $report.Facts.StateShaBefore = Sha $State
    $okPatch = (Sha $patchPck) -eq $Expected.PatchSha256
    $okBridge = (Sha $bridgePck) -eq $Expected.BridgeSha256
    Add-Step 'official patch and bridge match Linux' ($okPatch -and $okBridge) "patch=$okPatch bridge=$okBridge"
    if (-not ($okPatch -and $okBridge)) { throw 'official files differ from Linux; stop' }
    $report.Facts.BasePck = if (Test-Path -LiteralPath $basePck) { "present, $((Get-Item -LiteralPath $basePck).Length) bytes" } else { 'embedded in exe (no MidgardSurvivors.pck)' }

    # --- B. GDRE ------------------------------------------------------------
    $gdreDir = Join-Path $Kit 'gdre'
    $script:Gdre = Join-Path $gdreDir 'gdre_tools.exe'
    if (-not (Test-Path -LiteralPath $script:Gdre)) {
        $zip = Join-Path $Kit 'gdre.zip'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $sw = [Diagnostics.Stopwatch]::StartNew()
        (New-Object Net.WebClient).DownloadFile($Expected.GdreUrl, $zip)
        if ((Sha $zip) -ne $Expected.GdreZipSha256) { throw 'GDRE zip sha256 mismatch' }
        Expand-Archive -LiteralPath $zip -DestinationPath $gdreDir -Force
        Add-Step 'GDRE v2.7.4 downloaded' $true "$([int]$sw.Elapsed.TotalSeconds) s"
    }
    if (-not (Test-Path -LiteralPath $script:Gdre)) { throw "gdre_tools.exe not found in $gdreDir" }

    # --- C. Decompile parity (what a Windows rebuild after a Game update must do) ---
    $build = [Diagnostics.Stopwatch]::StartNew()
    foreach ($s in @(@{ Res = 'res://scripts/autoload/save.gdc'; Name = 'save' }, @{ Res = 'res://scripts/core/player.gdc'; Name = 'player' })) {
        $found = $null; $from = $null
        foreach ($src in @(@{ L = 'patch'; P = $patchPck }, @{ L = 'bridge'; P = $bridgePck }, @{ L = 'base'; P = $basePck })) {
            if (-not (Test-Path -LiteralPath $src.P)) { continue }
            $dir = Join-Path $Work "extract-$($s.Name)-$($src.L)"
            Run-Gdre @("--extract=$($src.P)", "--output=$dir", "--include=$($s.Res)") "extract-$($s.Name)-$($src.L)" | Out-Null
            $found = Get-ChildItem -LiteralPath $dir -Recurse -File -Filter "$($s.Name).gdc" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { $from = $src.L; break }
        }
        if (-not $found) { Add-Step "extract $($s.Name).gdc" $false 'not found in patch, bridge or base'; continue }
        $dec = Join-Path $Work "decompiled-$($s.Name)"
        Run-Gdre @("--decompile=$($found.FullName)", "--bytecode=$($Expected.Bytecode)", "--output=$dec") "decompile-$($s.Name)" | Out-Null
        $gd = Join-Path $dec "$($s.Name).gd"
        if (-not (Test-Path -LiteralPath $gd)) { Add-Step "decompile $($s.Name).gd" $false 'no output'; continue }
        $want = $Expected.Decompiled.($s.Name)
        $same = (Sha $gd) -eq $want; $sameText = (Sha-Text $gd) -eq $want
        Add-Step "decompile $($s.Name).gd equals Linux" ($same -or $sameText) "from=$from bytes=$same text=$sameText"
    }

    # --- D. Compile the kit sources -----------------------------------------
    $gdc = Join-Path $Work 'gdc'
    foreach ($n in @('save_hooked', 'player_patched', 'farmer')) {
        Run-Gdre @("--compile=$(Join-Path $Kit "src\$n.gd")", "--bytecode=$($Expected.Bytecode)", "--output=$gdc") "compile-$n" | Out-Null
        $f = Join-Path $gdc "$n.gdc"
        if (-not (Test-Path -LiteralPath $f)) { Add-Step "compile $n" $false 'no .gdc'; throw "compile $n failed" }
        Add-Step "compile $n equals Linux" ((Sha $f) -eq $Expected.Compiled.$n) (Sha $f)
    }

    # --- E. PCK patch -------------------------------------------------------
    $pck = Join-Path $Work 'patch_farmer.pck'
    Run-Gdre @("--pck-patch=$patchPck",
        "--patch-file=$(Join-Path $gdc 'save_hooked.gdc')=res://scripts/autoload/save.gdc",
        "--patch-file=$(Join-Path $gdc 'player_patched.gdc')=res://scripts/core/player.gdc",
        "--patch-file=$(Join-Path $gdc 'farmer.gdc')=res://scripts/core/farmer.gdc",
        "--output=$pck") 'pck-patch' | Out-Null
    if (-not (Test-Path -LiteralPath $pck)) { Add-Step 'pck-patch' $false 'no output'; throw 'pck-patch failed' }
    $build.Stop()
    $report.Facts.BuildSeconds = [int]$build.Elapsed.TotalSeconds
    $pckSha = Sha $pck
    $report.Facts.WindowsPckSha256 = $pckSha
    Add-Step 'patch_farmer.pck byte-identical to the Linux build' ($pckSha -eq $Expected.PckSha256) $pckSha
    $chk = Join-Path $Work 'pck-check'
    foreach ($r in @('res://scripts/autoload/save.gdc', 'res://scripts/core/player.gdc', 'res://scripts/core/farmer.gdc')) {
        Run-Gdre @("--extract=$pck", "--output=$chk", "--include=$r") 'pck-check' | Out-Null
    }
    foreach ($m in @(@{ F = 'save.gdc'; C = 'save_hooked' }, @{ F = 'player.gdc'; C = 'player_patched' }, @{ F = 'farmer.gdc'; C = 'farmer' })) {
        $e = Get-ChildItem -LiteralPath $chk -Recurse -File -Filter $m.F -ErrorAction SilentlyContinue | Select-Object -First 1
        $ok = $e -and ((Sha $e.FullName) -eq (Sha (Join-Path $gdc "$($m.C).gdc")))
        Add-Step "built pck carries $($m.F)" ([bool]$ok) ''
    }

    # --- F. Install into the real profile (backed up first) ----------------
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    $preexisting = @(Get-ChildItem -LiteralPath $DataDir -File | ForEach-Object { $_.Name })
    Get-ChildItem -LiteralPath $DataDir -File | Copy-Item -Destination $backup
    Copy-Item -LiteralPath $State -Destination (Join-Path $backup 'patches.state.json')
    Copy-Item -LiteralPath $pck -Destination (Join-Path $Patches 'patch_farmer.pck') -Force
    $installed = $true
    $st = Get-Content -LiteralPath $State -Raw -Encoding UTF8 | ConvertFrom-Json
    $st.file = 'patch_farmer.pck'
    $st | Add-Member -NotePropertyName farmer -NotePropertyValue 1 -Force
    [IO.File]::WriteAllText($State, ($st | ConvertTo-Json -Depth 5), $Utf8)
    [IO.File]::WriteAllBytes((Join-Path $DataDir 'farmer.cfg'), [IO.File]::ReadAllBytes((Join-Path $Kit 'farmer.cfg')))
    foreach ($n in @('farmer_status.json', 'farmer_session.json', 'farmer_stop', 'farmer_command')) {
        Remove-Item -LiteralPath (Join-Path $DataDir $n) -Force -ErrorAction SilentlyContinue
    }
    Add-Step 'installed into the real profile' $true "backup: $backup"

    # --- G. One offline run -------------------------------------------------
    $godotLog = Join-Path $DataDir 'logs\godot.log'
    $env:FARMER_SESSION = '1'
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $game = Start-Process -FilePath $Exe -ArgumentList '--headless' -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Out 'game.stdout.txt') -RedirectStandardError (Join-Path $Out 'game.stderr.txt')
    $done = $game.WaitForExit($RunTimeoutSec * 1000)
    Remove-Item Env:FARMER_SESSION
    if (-not $done) { Stop-Game }
    $sw.Stop()
    $report.Facts.RunSeconds = [int]$sw.Elapsed.TotalSeconds
    $report.Facts.RunExitCode = if ($done) { $game.ExitCode } else { 'timeout' }
    Add-Step 'game exited before timeout' $done "$([int]$sw.Elapsed.TotalSeconds) s, exit=$($report.Facts.RunExitCode)"
    foreach ($n in @('farmer_status.json', 'farmer.log', 'farmer_runs.jsonl')) {
        $p = Join-Path $DataDir $n
        if (Test-Path -LiteralPath $p) { Copy-Item -LiteralPath $p -Destination $Out }
    }
    if (Test-Path -LiteralPath $godotLog) { Copy-Item -LiteralPath $godotLog -Destination (Join-Path $Out 'godot.run.log') }
    $logs = @((Join-Path $Out 'game.stdout.txt'), (Join-Path $Out 'godot.run.log')) | Where-Object { Test-Path -LiteralPath $_ }
    $loaded = [bool]($logs -and (Select-String -LiteralPath $logs -Pattern 'FARMER_LOADED api=3' -SimpleMatch -Quiet))
    Add-Step 'FARMER_LOADED api=3' $loaded ''
    $finish = (Test-Path -LiteralPath (Join-Path $Out 'farmer.log')) -and [bool](Select-String -LiteralPath (Join-Path $Out 'farmer.log') -Pattern 'FINISH' -SimpleMatch -Quiet)
    Add-Step 'farmer.log has FINISH' $finish ''
    $errs = @(if ($logs) { Select-String -LiteralPath $logs -Pattern 'SCRIPT ERROR|Parse Error|Invalid call|Cannot call method' })
    Add-Step 'no script errors' ($errs.Count -eq 0) (($errs | Select-Object -First 3 | ForEach-Object { $_.Line }) -join ' | ')
    $sp = Join-Path $Out 'farmer_status.json'
    if (Test-Path -LiteralPath $sp) {
        $s = Get-Content -LiteralPath $sp -Raw -Encoding UTF8 | ConvertFrom-Json
        $ok = ($s.phase -eq 'done') -and $s.terminal -and (-not $s.failed) -and ([int]$s.totals.wins -ge 1) -and $s.last.victory -and ([int]$s.totals.kills -gt 0)
        Add-Step 'status: done, won, not failed' ([bool]$ok) "phase=$($s.phase) reason=$($s.finish_reason) runs=$($s.totals.runs) wins=$($s.totals.wins) kills=$($s.totals.kills) zeny=$($s.totals.zeny)"
    } else { Add-Step 'status: done, won, not failed' $false 'no farmer_status.json' }
    $report.Facts.FarmerLogTail = Tail (Join-Path $Out 'farmer.log') 25
    $report.Facts.GodotLogTail = Tail (Join-Path $Out 'godot.run.log') 25
}
catch {
    Add-Step 'aborted' $false $_.Exception.Message
}
finally {
    # --- H. Restore the official state (always) -----------------------------
    if ($installed) {
        Stop-Game
        Start-Sleep -Seconds 2
        Remove-Item -LiteralPath (Join-Path $Patches 'patch_farmer.pck') -Force -ErrorAction SilentlyContinue
        Copy-Item -LiteralPath (Join-Path $backup 'patches.state.json') -Destination $State -Force
        if (-not $KeepProfile) {
            Get-ChildItem -LiteralPath $DataDir -File | Where-Object { $preexisting -notcontains $_.Name } | Remove-Item -Force
            Get-ChildItem -LiteralPath $backup -File | Where-Object { $_.Name -ne 'patches.state.json' } |
                Copy-Item -Destination $DataDir -Force
        }
        $restored = (Sha $State) -eq $report.Facts.StateShaBefore
        $noPack = -not (Test-Path -LiteralPath (Join-Path $Patches 'patch_farmer.pck'))
        Add-Step 'official state restored' ($restored -and $noPack) "state=$restored pack-removed=$noPack profile-restored=$(-not $KeepProfile)"

        # --- I. Vanilla launch: no farmer, no script errors -----------------
        $godotLog = Join-Path $DataDir 'logs\godot.log'
        $g = Start-Process -FilePath $Exe -ArgumentList '--headless' -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $Out 'vanilla.stdout.txt') -RedirectStandardError (Join-Path $Out 'vanilla.stderr.txt')
        Start-Sleep -Seconds 25
        $alive = -not $g.HasExited
        Stop-Game
        Start-Sleep -Seconds 2
        if (Test-Path -LiteralPath $godotLog) { Copy-Item -LiteralPath $godotLog -Destination (Join-Path $Out 'godot.vanilla.log') }
        $vl = @((Join-Path $Out 'vanilla.stdout.txt'), (Join-Path $Out 'godot.vanilla.log')) | Where-Object { Test-Path -LiteralPath $_ }
        $farm = [bool]($vl -and (Select-String -LiteralPath $vl -Pattern 'FARMER_LOADED' -SimpleMatch -Quiet))
        $verr = @(if ($vl) { Select-String -LiteralPath $vl -Pattern 'SCRIPT ERROR|Parse Error' }).Count
        Add-Step 'vanilla game starts without the farmer' ($alive -and -not $farm -and $verr -eq 0) "alive-25s=$alive farmer=$farm script-errors=$verr"
        $report.Facts.StateAfter = [IO.File]::ReadAllText($State)
    }
    $path = Join-Path $Kit "03-windows-step7-$Stamp.json"
    [IO.File]::WriteAllText($path, ($report | ConvertTo-Json -Depth 6), $Utf8)
    Write-Host ''
    Write-Host "Report: $path"
    Write-Host "Logs:   $Out"
}
