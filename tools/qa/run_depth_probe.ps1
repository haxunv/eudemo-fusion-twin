param([string[]]$KitArguments = @())
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (@(Get-CimInstance Win32_Process -Filter "Name = 'kit.exe'").Count) {
    throw 'Stop the verified project Kit before running the depth probe; only one GPU Kit may run.'
}
. (Join-Path $projectRoot 'tools\runtime.ps1')
$runtimeConfig = Resolve-FusionRuntime -ProjectRoot $projectRoot
$output = Join-Path $projectRoot 'runtime\depth-probe'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$env:FUSION_TWIN_ROOT = $projectRoot
$env:OPENBLAS_NUM_THREADS = '4'
$app = Join-Path $projectRoot 'kit\apps\fusion_workflow_probe.kit'
$script = Join-Path $PSScriptRoot 'probe_depth.py'
$arguments = @('"' + $app + '"', '--no-window', '--exec', '"' + $script + '"',
    '--/log/file="' + (Join-Path $output 'kit.log') + '"', '--/log/outputStreamLevel=warning',
    '--/rtx/background/source/type=2', '--/rtx/background/source/color=[0.012,0.018,0.026]')
foreach ($folder in $runtimeConfig.ExtensionFolders) { $arguments += @('--ext-folder', '"' + $folder + '"') }
$arguments += $KitArguments
$process = Start-Process -FilePath $runtimeConfig.Kit -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $output 'stdout.log') -RedirectStandardError (Join-Path $output 'stderr.log')
Write-Output "Depth probe PID: $($process.Id). Reports: $output"
