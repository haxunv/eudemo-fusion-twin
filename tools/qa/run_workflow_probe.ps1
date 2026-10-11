param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $projectRoot 'tools\runtime.ps1')
$runtimeConfig = Resolve-FusionRuntime -ProjectRoot $projectRoot
$output = Join-Path $projectRoot 'runtime\workflow-probe'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$env:FUSION_TWIN_ROOT = $projectRoot
$env:OPENBLAS_NUM_THREADS = '4'
$app = Join-Path $projectRoot 'kit\apps\fusion_workflow_probe.kit'
$script = Join-Path $PSScriptRoot 'probe_workflow.py'
$arguments = @('"' + $app + '"', '--no-window', '--exec', '"' + $script + '"',
    '--/log/file="' + (Join-Path $output 'kit.log') + '"', '--/log/outputStreamLevel=warning')
foreach ($folder in $runtimeConfig.ExtensionFolders) { $arguments += @('--ext-folder', '"' + $folder + '"') }
$process = Start-Process -FilePath $runtimeConfig.Kit -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $output 'stdout.log') -RedirectStandardError (Join-Path $output 'stderr.log')
Write-Output "Isolated workflow probe PID: $($process.Id). Report: $output\report.json"
