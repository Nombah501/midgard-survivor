#Requires -Version 5.1
[CmdletBinding()]
param([string]$GameDir)

# This collector never starts the game. Its only output file is a new JSON report.
$gameName = '(?:midgard|ragnarok)[ ._-]*survivors?'

function Find-GameExeInFolder([string]$Directory) {
    $files = @(Get-ChildItem -LiteralPath $Directory -File -Filter '*.exe' -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike '*.console.exe' })
    $named = @($files | Where-Object { $_.BaseName -match $gameName })
    if ($named.Count) { return $named }
    if ($files.Count -eq 1) { return $files[0] }
}

function Get-PythonVersion([string]$Name) {
    $command = Get-Command -Name "$Name.exe" -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $command) { return }

    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $command.Path
    $start.Arguments = '--version'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    # Both the current Python install manager and the legacy launcher can auto-install.
    $start.EnvironmentVariables['PYTHON_MANAGER_AUTOMATIC_INSTALL'] = 'false'
    $start.EnvironmentVariables.Remove('PYLAUNCHER_ALLOW_INSTALL')
    $start.EnvironmentVariables.Remove('PYLAUNCHER_ALWAYS_INSTALL')
    try {
        $process = [System.Diagnostics.Process]::Start($start)
        try {
            $stderr = $process.StandardError.ReadToEndAsync()
            $stdout = $process.StandardOutput.ReadToEnd()
            $process.WaitForExit()
            $text = ($stdout + $stderr.GetAwaiter().GetResult()).Trim()
            if ($process.ExitCode -eq 0) { return [ordered]@{ Version = $text } }
            return [ordered]@{ Version = $null; ExitCode = $process.ExitCode; Error = $text }
        } finally {
            $process.Dispose()
        }
    } catch {
        return [ordered]@{ Version = $null; Error = $_.Exception.Message }
    }
}

$os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction SilentlyContinue
$osRegistry = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction SilentlyContinue
$systemDir = [Environment]::SystemDirectory
# The Administrators SID is present even if UAC filtered it to deny-only.
$groups = & (Join-Path $systemDir 'whoami.exe') /groups /fo csv /nh 2>&1
$isAdmin = if ($LASTEXITCODE -eq 0) { [bool]($groups -match '(?<![\d-])S-1-5-32-544(?![\d-])') }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
try {
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $isElevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} finally {
    $identity.Dispose()
}

$powercfg = Join-Path $systemDir 'powercfg.exe'
$activePlan = @(& $powercfg /getactivescheme 2>&1 | ForEach-Object { $_.ToString() })
$activePlanExit = $LASTEXITCODE
$sleepSettings = @(& $powercfg /query SCHEME_CURRENT SUB_SLEEP 2>&1 | ForEach-Object { $_.ToString() })
$sleepSettingsExit = $LASTEXITCODE

$userDataRoot = Join-Path $env:APPDATA 'Godot\app_userdata'
$userDataDirs = @(Get-ChildItem -LiteralPath $userDataRoot -Directory -Force -ErrorAction SilentlyContinue |
    Sort-Object Name | ForEach-Object {
        [pscustomobject]@{
            Name = $_.Name
            Path = $_.FullName
            HasProfile = Test-Path -LiteralPath (Join-Path $_.FullName 'profile.json') -PathType Leaf
            HasPatchState = Test-Path -LiteralPath (Join-Path $_.FullName 'patches\state.json') -PathType Leaf
        }
    })
$markedDirs = @($userDataDirs | Where-Object { $_.HasProfile -and $_.HasPatchState })
$namedDirs = @($userDataDirs | Where-Object { $_.Name -match "^$gameName$" })
$namedMarkedDirs = @($namedDirs | Where-Object { $_.HasProfile -and $_.HasPatchState })
$profile = if ($namedMarkedDirs.Count -eq 1) { $namedMarkedDirs[0] }
    elseif ($namedDirs.Count -eq 1) { $namedDirs[0] }
    elseif ($namedDirs.Count -eq 0 -and $markedDirs.Count -eq 1) { $markedDirs[0] }

$stateJson = $null
$patchErrors = @()
$patchFiles = @(if ($profile) {
    $patchDir = Join-Path $profile.Path 'patches'
    if ($profile.HasPatchState) {
        # [string] drops the provider NoteProperties (PSDrive, PSProvider) that ConvertTo-Json would expand into ~80 MB.
        try { $stateJson = [string](Get-Content -LiteralPath (Join-Path $patchDir 'state.json') -Raw -Encoding UTF8 -ErrorAction Stop) }
        catch { $patchErrors += $_.Exception.Message }
    }
    if (Test-Path -LiteralPath $patchDir -PathType Container) {
        try { $files = @(Get-ChildItem -LiteralPath $patchDir -File -Force -ErrorAction Stop | Sort-Object Name) }
        catch { $patchErrors += $_.Exception.Message; $files = @() }
        foreach ($file in $files) {
            $sha256 = $null
            try { $sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256 -ErrorAction Stop).Hash }
            catch { $patchErrors += $_.Exception.Message }
            [ordered]@{ Name = $file.Name; SizeBytes = $file.Length; SHA256 = $sha256 }
        }
    }
})

$gameCandidates = @(if ($GameDir) {
    Find-GameExeInFolder -Directory $GameDir
} else {
    $running = @(Get-Process | Where-Object { $_.ProcessName -match $gameName -and $_.ProcessName -notlike '*.console' } |
        ForEach-Object { if ($_.Path) { Get-Item -LiteralPath $_.Path -ErrorAction SilentlyContinue } })
    if ($running.Count) {
        $running
    } else {
        $searchRoots = @(
            (Join-Path $env:APPDATA 'itch\apps')
            (Join-Path $env:LOCALAPPDATA 'itch\apps')
            (Join-Path $env:USERPROFILE 'Downloads')
            [Environment]::GetFolderPath('DesktopDirectory')
            $PSScriptRoot
        )
        foreach ($root in ($searchRoots | Where-Object { $_ } | Sort-Object -Unique)) {
            Get-ChildItem -LiteralPath $root -File -Filter '*.exe' -ErrorAction SilentlyContinue |
                Where-Object { $_.BaseName -match $gameName -and $_.Name -notlike '*.console.exe' }
            Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match $gameName } |
                ForEach-Object { Find-GameExeInFolder -Directory $_.FullName }
        }
    }
})
$gameCandidates = @($gameCandidates | Sort-Object FullName -Unique)
$gameExe = if ($gameCandidates.Count -eq 1) { $gameCandidates[0] }

$report = [ordered]@{
    Windows = [ordered]@{
        Caption = $os.Caption
        Version = $os.Version
        DisplayVersion = $osRegistry.DisplayVersion
        Build = $osRegistry.CurrentBuildNumber
        BuildRevision = $osRegistry.UBR
    }
    Account = [ordered]@{ IsAdministrator = $isAdmin; IsElevated = $isElevated }
    Power = [ordered]@{
        ActivePlan = $activePlan
        ActivePlanExitCode = $activePlanExit
        SleepSettings = $sleepSettings
        SleepSettingsExitCode = $sleepSettingsExit
    }
    Python = [ordered]@{ Py = (Get-PythonVersion 'py'); Python = (Get-PythonVersion 'python') }
    UserDataRoot = $userDataRoot
    UserDataCandidates = $userDataDirs
    SelectedUserData = $profile
    PatchStateJson = $stateJson
    PatchFiles = $patchFiles
    PatchReadErrors = $patchErrors
    Game = [ordered]@{
        RequestedDirectory = $GameDir
        ExeCandidates = @($gameCandidates | ForEach-Object { $_.FullName })
        ExePath = $gameExe.FullName
        FileVersion = $gameExe.VersionInfo.FileVersion
        ProductVersion = $gameExe.VersionInfo.ProductVersion
    }
}

$json = ConvertTo-Json -InputObject $report -Depth 6
$json
$reportPath = Join-Path $PSScriptRoot ('03-windows-bench-{0}.json' -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$stream = [IO.File]::Open($reportPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    $bytes = [Text.Encoding]::UTF8.GetBytes($json + [Environment]::NewLine)
    $stream.Write($bytes, 0, $bytes.Length)
} finally {
    $stream.Dispose()
}
