param(
    [string]$PythonPath = 'D:\nvcode\fusion-env\Scripts\python.exe',
    [int]$Port = 8765,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimeDir = Join-Path $projectRoot 'runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $PythonPath)) {
    $PythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw 'Python environment not found. Set -PythonPath or install this project in .venv.'
}
$health = $null
try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -TimeoutSec 2 } catch { }
if (-not $health) {
    $env:PYTHONPATH = Join-Path $projectRoot 'app'
    $serverProcess = Start-Process -FilePath $PythonPath -ArgumentList @('-m', 'fusion_twin.server', '--port', "$Port") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'server.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'server.stderr.log') -PassThru
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/status" -TimeoutSec 1; break } catch { }
        if ($serverProcess.HasExited) { throw 'Application service failed; see runtime/server.stderr.log.' }
    }
}
if (-not $health -or $health.version -ne '0.1.0') { throw "Fusion Twin service unavailable on port $Port." }
& (Join-Path $projectRoot 'tools\launch_kit.ps1')
$url = "http://127.0.0.1:$Port"
Write-Host "Fusion Twin: $url"
Write-Host 'RTX first startup may take a minute. Logs are in runtime/.'
if (-not $NoBrowser) { Start-Process -FilePath $url }

