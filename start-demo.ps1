param(
    [string]$PythonPath,
    [string]$KitPath,
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$ServerOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimeDir = Join-Path $projectRoot 'runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
. (Join-Path $projectRoot 'tools\runtime.ps1')
Assert-FusionProjectPort -ProjectRoot $projectRoot -Port $Port
$runtimeConfig = Resolve-FusionRuntime -ProjectRoot $projectRoot -PythonPath $PythonPath -KitPath $KitPath
$PythonPath = $runtimeConfig.Python
$health = $null
try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -TimeoutSec 2 } catch { }
if ($health -and -not (Test-FusionServiceOwner -Health $health -ProjectRoot $projectRoot)) {
    throw "Port $Port is serving another project or an older service. Stop that service or choose another port."
}
if (-not $health) {
    $env:PYTHONPATH = Join-Path $projectRoot 'app'
    $serverProcess = Start-Process -FilePath $PythonPath -ArgumentList @('-m', 'fusion_twin.server', '--port', "$Port") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'server.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'server.stderr.log') -PassThru
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -TimeoutSec 1; break } catch { }
        if ($serverProcess.HasExited) { throw 'Application service failed; see runtime/server.stderr.log.' }
    }
}
if (-not (Test-FusionServiceOwner -Health $health -ProjectRoot $projectRoot)) {
    if ($serverProcess -and -not $serverProcess.HasExited) { $serverProcess.Kill(); $serverProcess.WaitForExit() }
    throw "Fusion Twin service unavailable on port $Port."
}
Save-FusionServerIdentity -ProjectRoot $projectRoot -ProcessId $health.pid
if (-not $ServerOnly) {
    & (Join-Path $projectRoot 'tools\launch_kit.ps1') -KitPath $runtimeConfig.Kit -PythonPath $PythonPath -Port $Port
}
$url = "http://127.0.0.1:$Port"
Write-Host "Fusion Twin: $url"
if (-not $ServerOnly) { Write-Host 'RTX first startup may take a minute. Logs are in runtime/.' }
if (-not $NoBrowser -and -not $ServerOnly) { Start-Process -FilePath $url }

