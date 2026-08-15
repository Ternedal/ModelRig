[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeDir = Join-Path $repoRoot 'validation\stage-a-runtime'
$backendExe = [IO.Path]::GetFullPath((Join-Path $runtimeDir 'modelrig-server-stage-a.exe'))

function Get-ListenerPid {
    param([int]$Port)
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) { return $null }
    return [int]$listener.OwningProcess
}

function Get-ProcessInfo {
    param([int]$ProcessId)
    try { return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop }
    catch { return $null }
}

function Stop-KnownListener {
    param([int]$Port, [ValidateSet('backend','worker')][string]$Kind)
    $processId = Get-ListenerPid -Port $Port
    if ($null -eq $processId) { return }
    $process = Get-ProcessInfo -ProcessId $processId
    if ($null -eq $process) { throw "Port $Port er optaget af en proces, der ikke kunne identificeres." }

    $known = $false
    if ($Kind -eq 'backend') {
        try {
            $path = [string]$process.ExecutablePath
            $known = (-not [string]::IsNullOrWhiteSpace($path)) -and
                [string]::Equals([IO.Path]::GetFullPath($path), $backendExe, [StringComparison]::OrdinalIgnoreCase)
        } catch { $known = $false }
    } else {
        $cmd = [string]$process.CommandLine
        $known = ([string]$process.Name -ieq 'python.exe') -and
            ($cmd -match 'uvicorn\s+app\.entrypoint:app') -and
            ($cmd -match '--port\s+8099')
    }

    if (-not $known) {
        throw "Port $Port bruges af en ukendt proces ($([string]$process.Name), PID $processId). Den stoppes ikke automatisk."
    }

    Write-Host "  Stopper tidligere kendt Stage A-$Kind (PID $processId)..." -ForegroundColor DarkGray
    Stop-Process -Id $processId -Force -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(20)
    while ($null -ne (Get-ListenerPid -Port $Port) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 250
    }
    if ($null -ne (Get-ListenerPid -Port $Port)) { throw "Port $Port blev ikke fri efter stop af Stage A-$Kind." }
}

if ($env:OS -ne 'Windows_NT') { throw 'Stage A runtime-cleanup må kun køres på Windows.' }
Stop-KnownListener -Port 8080 -Kind backend
Stop-KnownListener -Port 8099 -Kind worker
