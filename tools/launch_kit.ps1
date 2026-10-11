param([switch]$Foreground, [switch]$NoStreaming)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot 'runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$kitExecutable = 'D:\nvcode\fusion-twin\_build\windows-x86_64\release\kit\kit.exe'
if (-not (Test-Path -LiteralPath $kitExecutable)) { throw "NVIDIA Kit runtime missing: $kitExecutable" }
$pidPath = Join-Path $runtimeDir 'kit.pid'
if (Test-Path -LiteralPath $pidPath) {
    $existingPid = [int](Get-Content -LiteralPath $pidPath)
    $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $existingPid" -ErrorAction SilentlyContinue
    if ($existingProcess -and $existingProcess.Name -eq 'kit.exe' -and $existingProcess.CommandLine -like '*fusion_twin.kit*') { Write-Output "Kit is already running: $existingPid"; return }
}
$env:FUSION_TWIN_ROOT = $projectRoot
[IO.File]::WriteAllText((Join-Path $runtimeDir 'renderer.json'), '{"ready":false,"status":"starting"}')
$env:OPENBLAS_NUM_THREADS = '4'
$appFile = Join-Path $projectRoot 'kit\apps\fusion_twin.kit'
$logFile = Join-Path $runtimeDir 'kit.log'
$argsList = @('"' + $appFile + '"', '--no-window', '--/log/file="' + $logFile + '"', '--/log/fileLogLevel=info', '--/log/outputStreamLevel=warning', '--/app/settings/persistent=false')
if ($NoStreaming) { $argsList += '--/exts/omni.kit.livestream.app/primaryStream/streamType=' }
if ($Foreground) {
    & $kitExecutable @argsList
} else {
    $kitProcess = Start-Process -FilePath $kitExecutable -ArgumentList $argsList -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'kit.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'kit.stderr.log')
    Set-Content -LiteralPath $pidPath -Value $kitProcess.Id
    Write-Output "Kit launched in background. PID $($kitProcess.Id). Status: $runtimeDir\renderer.json"
}
