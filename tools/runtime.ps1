function Resolve-FusionRuntime {
    param([string]$ProjectRoot, [string]$PythonPath, [string]$KitPath)
    $configPath = Join-Path $ProjectRoot 'runtime.local.json'
    $config = @{}
    if (Test-Path -LiteralPath $configPath) {
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    }
    if (-not $PythonPath) { $PythonPath = $env:FUSION_PYTHON }
    if (-not $PythonPath) { $PythonPath = $config.python }
    if (-not $PythonPath) { $PythonPath = '.venv\Scripts\python.exe' }
    if (-not $KitPath) { $KitPath = $env:FUSION_KIT_EXE }
    if (-not $KitPath) { $KitPath = $config.kit_executable }
    if (-not $KitPath) { throw 'Configure runtime.local.json or FUSION_KIT_EXE. See runtime.example.json.' }
    foreach ($entry in @(@{Name='python'; Path=$PythonPath}, @{Name='kit'; Path=$KitPath})) {
        if (-not [IO.Path]::IsPathRooted($entry.Path)) { $entry.Path = Join-Path $ProjectRoot $entry.Path }
        if (-not (Test-Path -LiteralPath $entry.Path -PathType Leaf)) { throw "Missing $($entry.Name) runtime: $($entry.Path)" }
        $entry.Path = (Resolve-Path -LiteralPath $entry.Path).Path
        if ($entry.Name -eq 'python') { $PythonPath = $entry.Path } else { $KitPath = $entry.Path }
    }
    $folders = @($config.extension_folders)
    if ($env:FUSION_EXT_FOLDERS) { $folders = @($env:FUSION_EXT_FOLDERS -split ';') }
    $resolvedFolders = @()
    foreach ($folder in $folders) {
        if (-not $folder) { continue }
        if (-not [IO.Path]::IsPathRooted($folder)) { $folder = Join-Path $ProjectRoot $folder }
        if (-not (Test-Path -LiteralPath $folder -PathType Container)) { throw "Missing extension folder: $folder" }
        $resolvedFolders += (Resolve-Path -LiteralPath $folder).Path
    }
    return @{ Python=$PythonPath; Kit=$KitPath; ExtensionFolders=$resolvedFolders }
}

function Test-FusionServiceOwner {
    param($Health, [string]$ProjectRoot)
    return $Health -and $Health.version -eq '0.1.0' -and $Health.project_root -and
        [IO.Path]::GetFullPath($Health.project_root).TrimEnd('\', '/') -eq [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
}

function Test-FusionKitOwner {
    param($Process, [string]$ProjectRoot)
    $appFile = (Join-Path $ProjectRoot 'kit\apps\fusion_twin.kit').Replace('\', '/')
    return $Process -and $Process.Name -eq 'kit.exe' -and $Process.CommandLine -and
        $Process.CommandLine.Replace('\', '/') -match ('(?:^|["\s])' + [regex]::Escape($appFile) + '(?:["\s]|$)')
}

function Assert-FusionProjectPort {
    param([string]$ProjectRoot, [int]$Port)
    $runtimeDir = Join-Path $ProjectRoot 'runtime'
    $identity = $null
    $identityPath = Join-Path $runtimeDir 'server.identity.json'
    if (Test-Path -LiteralPath $identityPath) {
        $identity = Get-Content -LiteralPath $identityPath -Raw | ConvertFrom-Json
    }
    $serverIds = @()
    if ($identity) { $serverIds += [int]$identity.pid }
    $serverPidPath = Join-Path $runtimeDir 'server.pid'
    if (Test-Path -LiteralPath $serverPidPath) { $serverIds += [int](Get-Content -LiteralPath $serverPidPath -Raw) }
    foreach ($serverId in ($serverIds | Select-Object -Unique)) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $serverId" -ErrorAction SilentlyContinue
        if (-not $process -or $process.CommandLine -notmatch '(?:^|["\s])fusion_twin\.server(?:["\s]|$)') { continue }
        $serverPort = 8765
        if ($process.CommandLine -match '(?:^|["\s])--port(?:=|\s+)"?(\d+)(?:["\s]|$)') { $serverPort = [int]$Matches[1] }
        if ($serverPort -eq $Port) { continue }
        $owned = $identity -and $identity.pid -eq $serverId -and $identity.project_root -and
            [IO.Path]::GetFullPath($identity.project_root).TrimEnd('\', '/') -eq [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/') -and
            $identity.created_ticks -eq $process.CreationDate.ToUniversalTime().Ticks
        if (-not $owned) {
            $health = $null
            try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:$serverPort/api/status" -TimeoutSec 2 } catch { }
            $owned = (Test-FusionServiceOwner -Health $health -ProjectRoot $ProjectRoot) -and $health.pid -eq $serverId
        }
        if ($owned) { throw "This project already has an application service on port $serverPort (PID $serverId); cannot also start it on port $Port." }
    }
    $kitPidPath = Join-Path $runtimeDir 'kit.pid'
    if (Test-Path -LiteralPath $kitPidPath) {
        $kitId = [int](Get-Content -LiteralPath $kitPidPath -Raw)
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $kitId" -ErrorAction SilentlyContinue
        if (Test-FusionKitOwner -Process $process -ProjectRoot $ProjectRoot) {
            $kitPort = 8765
            if ($process.CommandLine -match '(?:^|["\s])--/fusion/serverUrl=([^"\s]+)') { $kitPort = ([uri]$Matches[1]).Port }
            if ($kitPort -ne $Port) { throw "This project's Kit (PID $kitId) targets port $kitPort; cannot reuse it for port $Port." }
        }
    }
}

function Save-FusionServerIdentity {
    param([string]$ProjectRoot, [int]$ProcessId)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    if (-not $process) { throw "Application service process $ProcessId has exited." }
    $identity = @{ project_root=[IO.Path]::GetFullPath($ProjectRoot); pid=$ProcessId; created_ticks=$process.CreationDate.ToUniversalTime().Ticks }
    $identity | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ProjectRoot 'runtime\server.identity.json') -Encoding UTF8
}
