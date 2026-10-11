$ErrorActionPreference = 'Stop'
$runtimeDir = Join-Path $PSScriptRoot 'runtime'
. (Join-Path $PSScriptRoot 'tools\runtime.ps1')
foreach ($pidFile in @('server.pid', 'kit.pid')) {
    $file = Join-Path $runtimeDir $pidFile
    if (Test-Path -LiteralPath $file) {
        $taskProcessId = [int](Get-Content -LiteralPath $file -Raw)
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskProcessId" -ErrorAction SilentlyContinue
        if (-not $taskProcess) { continue }
        $owned = Test-FusionKitOwner -Process $taskProcess -ProjectRoot $PSScriptRoot
        if ($pidFile -eq 'server.pid') {
            $owned = $false
            $identityPath = Join-Path $runtimeDir 'server.identity.json'
            if (Test-Path -LiteralPath $identityPath) {
                $identity = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
                $owned = $identity.project_root -eq $PSScriptRoot -and $identity.pid -eq $taskProcessId -and
                    $identity.created_ticks -eq $taskProcess.CreationDate.ToUniversalTime().Ticks -and
                    $taskProcess.CommandLine -like '*fusion_twin.server*'
            }
        }
        if (-not $owned) { throw "PID $taskProcessId is not verified as belonging to this project; left running." }
        if ($owned) {
            $processHandle = Get-Process -Id $taskProcessId -ErrorAction SilentlyContinue
            if ($processHandle -and -not $processHandle.HasExited) {
                Stop-Process -InputObject $processHandle -Force
                $exited = $processHandle.WaitForExit(30000)
                $processHandle.Refresh()
                if (-not $exited -and -not $processHandle.HasExited) {
                    $remaining = Get-CimInstance Win32_Process -Filter "ProcessId = $taskProcessId" -ErrorAction SilentlyContinue
                    if ($remaining -and $remaining.CreationDate -eq $taskProcess.CreationDate) {
                        throw "Process $taskProcessId did not exit; runtime files remain in use."
                    }
                }
            }
            Write-Host "Stopped $pidFile ($taskProcessId)"
        }
    }
}
