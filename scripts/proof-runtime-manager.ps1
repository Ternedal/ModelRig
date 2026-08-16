[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('suspend','resume')]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$StatePath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeDir = Join-Path $root 'validation\stage-a-runtime'
$stageBackend = [IO.Path]::GetFullPath((Join-Path $runtimeDir 'modelrig-server-stage-a.exe'))
$normalServerPaths = @(
    (Join-Path $root 'scripts\modelrig-server-windows-x64.exe'),
    (Join-Path $root 'modelrig-server-windows-x64.exe'),
    (Join-Path $env:USERPROFILE 'Desktop\modelrig-server-windows-x64.exe')
) | ForEach-Object { [IO.Path]::GetFullPath($_) }
$normalWorkerExe = [IO.Path]::GetFullPath((Join-Path $root 'worker\modelrig-worker-windows-x64.exe'))
$stateFull = [IO.Path]::GetFullPath($StatePath)

function Get-ListenerPid {
    param([int]$Port)
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $listener) { return $null }
    return [int]$listener.OwningProcess
}

function Get-ProcessInfo {
    param([int]$ProcessId)
    try { return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop }
    catch { return $null }
}

function Wait-PortFree {
    param([int]$Port, [int]$Seconds = 60)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ($null -ne (Get-ListenerPid -Port $Port) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
    if ($null -ne (Get-ListenerPid -Port $Port)) { throw "Port $Port blev ikke fri inden for $Seconds sekunder." }
}

function Wait-PortUp {
    param([int]$Port, [int]$Seconds = 90)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ($null -eq (Get-ListenerPid -Port $Port) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
    if ($null -eq (Get-ListenerPid -Port $Port)) { throw "Port $Port kom ikke tilbage inden for $Seconds sekunder." }
}

function Path-EqualsAny {
    param([string]$Path, [string[]]$Allowed)
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    try { $full = [IO.Path]::GetFullPath($Path) } catch { return $false }
    foreach ($candidate in $Allowed) {
        if ([string]::Equals($full, $candidate, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Get-ManualPlan {
    $plan = @()
    foreach ($entry in @(@{Port=8080;Kind='backend'}, @{Port=8099;Kind='worker'})) {
        $pidValue = Get-ListenerPid -Port $entry.Port
        if ($null -eq $pidValue) { continue }
        $process = Get-ProcessInfo -ProcessId $pidValue
        if ($null -eq $process) { throw "Port $($entry.Port) er optaget af en proces, der ikke kunne identificeres." }
        $path = [string]$process.ExecutablePath
        $cmd = [string]$process.CommandLine

        if ($entry.Kind -eq 'backend') {
            if (Path-EqualsAny -Path $path -Allowed @($stageBackend)) {
                $plan += [pscustomobject]@{ Port=8080; Kind='stage-backend'; Normal=$false; Pid=$pidValue; Path=$path; CommandLine=$cmd }
                continue
            }
            if (Path-EqualsAny -Path $path -Allowed $normalServerPaths) {
                $plan += [pscustomobject]@{ Port=8080; Kind='normal-backend'; Normal=$true; Pid=$pidValue; Path=$path; CommandLine=$cmd }
                continue
            }
        } else {
            $isPythonWorker = ([string]$process.Name -ieq 'python.exe') -and ($cmd -match 'uvicorn\s+app\.entrypoint:app') -and ($cmd -match '--port\s+8099')
            $isStagePythonWorker = $isPythonWorker -and ($cmd -match '\s-u\s+-m\s+uvicorn')
            if ($isStagePythonWorker) {
                $plan += [pscustomobject]@{ Port=8099; Kind='stage-worker'; Normal=$false; Pid=$pidValue; Path=$path; CommandLine=$cmd }
                continue
            }
            if ($isPythonWorker) {
                $plan += [pscustomobject]@{ Port=8099; Kind='normal-python-worker'; Normal=$true; Pid=$pidValue; Path=$path; CommandLine=$cmd }
                continue
            }
            if (Path-EqualsAny -Path $path -Allowed @($normalWorkerExe)) {
                $plan += [pscustomobject]@{ Port=8099; Kind='normal-worker-exe'; Normal=$true; Pid=$pidValue; Path=$path; CommandLine=$cmd }
                continue
            }
        }
        throw "Port $($entry.Port) bruges af en ukendt proces ($([string]$process.Name), PID $pidValue). Den stoppes ikke automatisk."
    }
    return @($plan)
}

function Write-State {
    param([hashtable]$Value)
    $parent = Split-Path $stateFull -Parent
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $stateFull -Encoding UTF8
}

function Suspend-NormalRuntime {
    Remove-Item -LiteralPath $stateFull -Force -ErrorAction SilentlyContinue

    $task = $null
    try { $task = Get-ScheduledTask -TaskName 'KalivSupervisor' -ErrorAction Stop } catch { }
    if ($null -ne $task -and [string]$task.State -eq 'Running') {
        Write-State @{ schema='modelrig-proof-runtime-suspend/v1'; mode='scheduled-supervisor'; task='KalivSupervisor'; root=$root }
        Write-Host '  Suspenderer den kendte KalivSupervisor-task under proof-kampagnen...' -ForegroundColor DarkGray
        Stop-ScheduledTask -TaskName 'KalivSupervisor' -ErrorAction Stop
        Wait-PortFree -Port 8080
        Wait-PortFree -Port 8099
        Write-Host '  Normal Kaliv-supervisor er suspenderet kontrolleret.' -ForegroundColor Green
        return
    }

    # Classify every occupied proof port BEFORE stopping anything. One unknown
    # owner aborts the whole operation without partially taking the rig down.
    $plan = Get-ManualPlan
    $normal = @($plan | Where-Object { $_.Normal })
    if ($normal.Count -eq 0) { return }

    Write-State @{
        schema='modelrig-proof-runtime-suspend/v1'
        mode='manual-known-runtime'
        root=$root
        processes=@($normal | ForEach-Object { @{kind=$_.Kind;path=$_.Path;command_line=$_.CommandLine;port=$_.Port} })
    }
    foreach ($item in $normal) {
        Write-Host "  Suspenderer kendt normal ModelRig-$($item.Kind) (PID $($item.Pid))..." -ForegroundColor DarkGray
        Stop-Process -Id $item.Pid -Force -ErrorAction Stop
    }
    foreach ($item in $normal) { Wait-PortFree -Port $item.Port }
    Write-Host '  Kendt normal ModelRig-runtime er suspenderet kontrolleret.' -ForegroundColor Green
}

function Restore-EnvironmentValue {
    param([string]$Name, [AllowNull()][string]$Value)
    [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
}

function Resume-NormalRuntime {
    if (-not (Test-Path -LiteralPath $stateFull -PathType Leaf)) { return }
    $state = Get-Content -LiteralPath $stateFull -Raw | ConvertFrom-Json
    if ([string]$state.schema -ne 'modelrig-proof-runtime-suspend/v1') { throw 'Ukendt runtime-suspend state; normal runtime startes ikke automatisk.' }
    if ([string]$state.root -ne $root) { throw 'Runtime-suspend state tilhører en anden repo-rod; normal runtime startes ikke automatisk.' }

    if ([string]$state.mode -eq 'scheduled-supervisor') {
        if ($null -ne (Get-ListenerPid -Port 8080) -or $null -ne (Get-ListenerPid -Port 8099)) {
            throw 'Proof-runtime bruger stadig 8080/8099; KalivSupervisor startes ikke oveni.'
        }
        Write-Host '  Genstarter den kendte KalivSupervisor-task...' -ForegroundColor DarkGray
        Start-ScheduledTask -TaskName ([string]$state.task) -ErrorAction Stop
        Wait-PortUp -Port 8080
        Wait-PortUp -Port 8099
        Remove-Item -LiteralPath $stateFull -Force
        Write-Host '  Normal Kaliv-supervisor er gendannet.' -ForegroundColor Green
        return
    }

    if ([string]$state.mode -ne 'manual-known-runtime') { throw 'Ukendt runtime-suspend mode; normal runtime startes ikke automatisk.' }
    $processes = @($state.processes)
    foreach ($item in $processes) {
        $port = [int]$item.port
        if ($null -ne (Get-ListenerPid -Port $port)) { throw "Port $port er optaget; normal ModelRig-runtime startes ikke oveni." }
    }

    foreach ($item in $processes) {
        $kind = [string]$item.kind
        $path = [string]$item.path
        if ($kind -eq 'normal-backend') {
            if (-not (Path-EqualsAny -Path $path -Allowed $normalServerPaths)) { throw 'Den gemte normale backend-path er ikke længere tilladt.' }
            $oldHost = [Environment]::GetEnvironmentVariable('MODELRIG_HOST','Process')
            try {
                [Environment]::SetEnvironmentVariable('MODELRIG_HOST','0.0.0.0','Process')
                Start-Process -FilePath $path -WorkingDirectory (Split-Path $path -Parent) | Out-Null
            } finally { Restore-EnvironmentValue -Name 'MODELRIG_HOST' -Value $oldHost }
        } elseif ($kind -eq 'normal-python-worker') {
            $oldTools = [Environment]::GetEnvironmentVariable('KALIV_TOOLS_ENABLED','Process')
            $oldPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH','Process')
            try {
                [Environment]::SetEnvironmentVariable('KALIV_TOOLS_ENABLED','1','Process')
                [Environment]::SetEnvironmentVariable('PYTHONPATH',(Join-Path $root 'worker'),'Process')
                Start-Process -FilePath $path -ArgumentList '-m','uvicorn','app.entrypoint:app','--host','127.0.0.1','--port','8099' -WorkingDirectory $root | Out-Null
            } finally {
                Restore-EnvironmentValue -Name 'KALIV_TOOLS_ENABLED' -Value $oldTools
                Restore-EnvironmentValue -Name 'PYTHONPATH' -Value $oldPythonPath
            }
        } elseif ($kind -eq 'normal-worker-exe') {
            if (-not (Path-EqualsAny -Path $path -Allowed @($normalWorkerExe))) { throw 'Den gemte normale worker-path er ikke længere tilladt.' }
            Start-Process -FilePath $path -WorkingDirectory (Split-Path $path -Parent) | Out-Null
        } else {
            throw "Ukendt gemt normal runtime-kind: $kind"
        }
    }
    foreach ($item in $processes) { Wait-PortUp -Port ([int]$item.port) }
    Remove-Item -LiteralPath $stateFull -Force
    Write-Host '  Kendt normal ModelRig-runtime er gendannet.' -ForegroundColor Green
}

if ($env:OS -ne 'Windows_NT') { throw 'Proof runtime-manager må kun køres på Windows-riggen.' }
if ($Action -eq 'suspend') { Suspend-NormalRuntime } else { Resume-NormalRuntime }
