param([switch]$Foreground, [switch]$NoStreaming, [string]$KitPath, [string]$PythonPath, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot 'runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
. (Join-Path $PSScriptRoot 'runtime.ps1')
Assert-FusionProjectPort -ProjectRoot $projectRoot -Port $Port
$runtimeConfig = Resolve-FusionRuntime -ProjectRoot $projectRoot -KitPath $KitPath -PythonPath $PythonPath
$kitExecutable = $runtimeConfig.Kit
$pidPath = Join-Path $runtimeDir 'kit.pid'
if (Test-Path -LiteralPath $pidPath) {
    $existingPid = [int](Get-Content -LiteralPath $pidPath)
    $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $existingPid" -ErrorAction SilentlyContinue
    if (Test-FusionKitOwner -Process $existingProcess -ProjectRoot $projectRoot) { Write-Output "Kit is already running: $existingPid"; return }
}
$env:FUSION_TWIN_ROOT = $projectRoot
[IO.File]::WriteAllText((Join-Path $runtimeDir 'renderer.json'), '{"ready":false,"status":"starting"}')
$env:OPENBLAS_NUM_THREADS = '4'
$appFile = Join-Path $projectRoot 'kit\apps\fusion_twin.kit'
$logFile = Join-Path $runtimeDir 'kit.log'
$argsList = @($appFile, '--no-window', "--/log/file=$logFile", '--/log/fileLogLevel=info', '--/log/outputStreamLevel=warning', '--/app/settings/persistent=false')
$argsList += "--/fusion/serverUrl=http://127.0.0.1:$Port"
foreach ($folder in $runtimeConfig.ExtensionFolders) { $argsList += @('--ext-folder', $folder) }
if ($NoStreaming) { $argsList += '--/exts/omni.kit.livestream.app/primaryStream/streamType=' }
if ($Foreground) {
    & $kitExecutable @argsList
} else {
    $quotedArgs = @($argsList | ForEach-Object { '"' + $_ + '"' })
    $kitProcess = Start-Process -FilePath $kitExecutable -ArgumentList $quotedArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'kit.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'kit.stderr.log')
    Set-Content -LiteralPath $pidPath -Value $kitProcess.Id
    Write-Output "Kit launched in background. PID $($kitProcess.Id). Status: $runtimeDir\renderer.json"
}
