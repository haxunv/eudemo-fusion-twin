$ErrorActionPreference = 'Stop'
$runtimeDir = Join-Path $PSScriptRoot 'runtime'
foreach ($pidFile in @('server.pid', 'kit.pid')) {
    $file = Join-Path $runtimeDir $pidFile
    if (Test-Path -LiteralPath $file) {
        $taskProcessId = [int](Get-Content -LiteralPath $file -Raw)
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskProcessId" -ErrorAction SilentlyContinue
        if ($taskProcess -and ($taskProcess.CommandLine -like '*fusion_twin.server*' -or $taskProcess.CommandLine -like '*fusion_twin.kit*')) {
            Stop-Process -Id $taskProcessId
            Write-Host "Stopped $pidFile ($taskProcessId)"
        }
    }
}
