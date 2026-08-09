[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet(
        "PrepareOff",
        "Enable",
        "Grant",
        "Revoke",
        "Regrant",
        "RestartWorker",
        "RestartBackend",
        "MutateCampaignSnapshot",
        "MutateSummarySnapshot",
        "Stop",
        "Status"
    )]
    [string]$Action,
    [string]$ExpectedSha,
    [string]$DeviceId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "agent4-physical-read-common.ps1")

$requiredCheckpoints = @(
    "default_off_feature_locked",
    "default_off_no_worker_fallback",
    "paired_without_grant_403",
    "paired_without_grant_locked_no_stale",
    "grant_same_token_200",
    "campaign_paging_no_loss",
    "timeline_paging_no_loss",
    "evidence_paging_no_loss",
    "detail_verification_matches",
    "no_write_controls",
    "stale_campaign_record_422",
    "stale_summary_422",
    "revoke_same_token_403",
    "revoke_clears_data",
    "restart_does_not_restore_grant",
    "regrant_same_token_200",
    "backend_restart_recovery",
    "worker_restart_recovery",
    "network_recovery",
    "malformed_schema_fail_closed",
    "not_found_fail_closed"
)

function Read-Observations {
    if (-not (Test-Path -LiteralPath $script:observationsPath -PathType Leaf)) {
        throw "A4-18 observationsfil mangler. Kør PrepareOff først."
    }
    return Get-Content -LiteralPath $script:observationsPath -Raw | ConvertFrom-Json
}

function Initialize-Observations {
    $items = [ordered]@{}
    foreach ($name in $requiredCheckpoints) {
        $items[$name] = [ordered]@{
            status = "pending"
            observed_at = $null
            note = $null
            http_status = $null
            route = $null
            request_id = $null
            payload_sha256 = $null
            cursor_sha256 = $null
            screenshot = $null
        }
    }
    [ordered]@{
        schema = "modelrig-agent4/physical-read-observations/v2"
        expected_sha = Get-ExactHead
        checkpoints = $items
        production_activation = $false
    } | ConvertTo-Json -Depth 20 |
        Set-Content -LiteralPath $script:observationsPath -Encoding UTF8
}

function Assert-CheckpointsPassed {
    param([Parameter(Mandatory = $true)][string[]]$Names)
    $observations = Read-Observations
    $missing = @()
    foreach ($name in $Names) {
        if ([string]$observations.checkpoints.$name.status -ne "pass") {
            $missing += $name
        }
    }
    if ($missing.Count -gt 0) {
        throw "Fasen er låst. Disse checkpoints er ikke bestået: $($missing -join ', ')."
    }
}

function Assert-StatePhase {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)][string[]]$Allowed)
    if ($Allowed -notcontains [string]$State.phase) {
        throw "Handling er ikke tilladt i fase '$($State.phase)'. Forventede: $($Allowed -join ', ')."
    }
}

function Resolve-DeviceId {
    param([string]$Requested)
    if (-not [string]::IsNullOrWhiteSpace($Requested)) { return $Requested.Trim() }
    if (-not (Test-Path -LiteralPath $script:pairingData -PathType Leaf)) {
        throw "Pairing-store mangler."
    }
    $store = Get-Content -LiteralPath $script:pairingData -Raw | ConvertFrom-Json
    $devices = @($store.devices)
    if ($devices.Count -ne 1) {
        throw "Der skal være præcis én parret fysisk enhed; fandt $($devices.Count). Brug -DeviceId ved et bevidst valg."
    }
    return [string]$devices[0].id
}

function Set-ReadGrantTransition {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("grant", "revoke", "regrant")][string]$Transition,
        [string]$RequestedDeviceId
    )
    $state = Read-OperatorState
    Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
    switch ($Transition) {
        "grant" {
            Assert-StatePhase -State $state -Allowed @("enabled_no_grant")
            Assert-CheckpointsPassed -Names @("paired_without_grant_403", "paired_without_grant_locked_no_stale")
            $enabled = $true
            $nextPhase = "granted"
        }
        "revoke" {
            Assert-StatePhase -State $state -Allowed @("granted")
            Assert-CheckpointsPassed -Names @(
                "grant_same_token_200",
                "campaign_paging_no_loss",
                "timeline_paging_no_loss",
                "evidence_paging_no_loss",
                "detail_verification_matches",
                "no_write_controls",
                "stale_campaign_record_422",
                "stale_summary_422"
            )
            $enabled = $false
            $nextPhase = "revoked"
        }
        "regrant" {
            Assert-StatePhase -State $state -Allowed @("revoked")
            Assert-CheckpointsPassed -Names @(
                "revoke_same_token_403",
                "revoke_clears_data",
                "restart_does_not_restore_grant"
            )
            $enabled = $true
            $nextPhase = "regranted"
        }
    }
    $resolvedDevice = Resolve-DeviceId -Requested $RequestedDeviceId
    $adminKey = Get-AdminKey
    try {
        $env:MODELRIG_ADMIN_KEY = $adminKey
        if ($enabled) {
            & $script:grantExe -grant $resolvedDevice -url "http://127.0.0.1:8080"
        }
        else {
            & $script:grantExe -revoke $resolvedDevice -url "http://127.0.0.1:8080"
        }
        if ($LASTEXITCODE -ne 0) { throw "Grant CLI afviste ændringen." }
    }
    finally {
        Remove-Item Env:MODELRIG_ADMIN_KEY -ErrorAction SilentlyContinue
    }
    $state.device_id = $resolvedDevice
    $state.phase = $nextPhase
    Write-OperatorState -State $state
}

function Show-PhysicalStatus {
    if (-not (Test-Path -LiteralPath $script:statePath -PathType Leaf)) {
        Write-Host "A4-18 er ikke forberedt."
        return
    }
    $state = Read-OperatorState
    $observations = Read-Observations
    $passed = @($requiredCheckpoints | Where-Object {
        [string]$observations.checkpoints.$_.status -eq "pass"
    }).Count
    [ordered]@{
        expected_sha = [string]$state.expected_sha
        phase = [string]$state.phase
        mode = [string]$state.mode
        lan_url = [string]$state.lan_url
        backend_pid = [int]$state.backend_pid
        worker_pid = [int]$state.worker_pid
        device_id = $state.device_id
        passed_checkpoints = $passed
        total_checkpoints = $requiredCheckpoints.Count
        last_mutation = $state.last_mutation
        receipt = $state.receipt
        production_activation = $false
    } | ConvertTo-Json -Depth 8
}

Assert-WindowsAdministrator
New-Item -ItemType Directory -Path $script:runtimeDir -Force | Out-Null

switch ($Action) {
    "PrepareOff" {
        if ([string]::IsNullOrWhiteSpace($ExpectedSha)) { throw "PrepareOff kræver -ExpectedSha." }
        Assert-ExactCleanHead -RequiredSha $ExpectedSha
        if (Test-Path -LiteralPath $script:statePath -PathType Leaf) {
            Stop-RecordedStack | Out-Null
        }
        Remove-Item -LiteralPath $script:runtimeDir -Recurse -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Path $script:runtimeDir -Force | Out-Null
        try {
            New-AdminKey
            $apk = Build-And-InstallPhysicalArtifacts
            $lanAddress = Resolve-LanAddress
            $state = [pscustomobject][ordered]@{
                schema = "modelrig-agent4/physical-read-operator-state/v2"
                created_at = (Get-Date).ToUniversalTime().ToString("o")
                updated_at = (Get-Date).ToUniversalTime().ToString("o")
                expected_sha = $ExpectedSha
                branch = (& git -C $script:repoRoot branch --show-current).Trim()
                phase = "preparing"
                mode = "off"
                lan_url = "http://${lanAddress}:8080"
                pairing_code = $null
                pairing_expires_at = $null
                backend_pid = 0
                worker_pid = 0
                backend_version = $null
                worker_version = $null
                device_id = $null
                apk = $apk
                mutation_receipts = @()
                last_mutation = $null
                receipt = $null
                human_decision = $null
                production_activation = $false
            }
            Write-OperatorState -State $state
            Initialize-Observations
            Start-Stack -Mode off -State $state
            $state = Read-OperatorState
            $pairing = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v1/pair/start" -TimeoutSec 10
            $state.pairing_code = [string]$pairing.code
            $state.pairing_expires_at = [string]$pairing.expires_at
            Write-OperatorState -State $state
        }
        catch {
            Stop-CurrentExpectedListeners
            Remove-Item -LiteralPath $script:adminKeyFile -Force -ErrorAction SilentlyContinue
            throw
        }
        Write-Host "A4-18 DEFAULT-OFF STACK ER KLAR" -ForegroundColor Green
        Write-Host "Server-URL:   $($state.lan_url)" -ForegroundColor Cyan
        Write-Host "Parringskode: $($state.pairing_code)" -ForegroundColor Yellow
    }
    "Enable" {
        $state = Read-OperatorState
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Assert-StatePhase -State $state -Allowed @("default_off")
        Assert-CheckpointsPassed -Names @("default_off_feature_locked", "default_off_no_worker_fallback")
        [void](Resolve-DeviceId -Requested $null)
        Stop-RecordedStack -PreserveAdminKey | Out-Null
        Start-Stack -Mode enabled -State $state
        Write-Host "Agent 4 er enabled; Pixel har stadig intet grant." -ForegroundColor Green
    }
    "Grant" {
        Set-ReadGrantTransition -Transition grant -RequestedDeviceId $DeviceId
        Write-Host "agent4:read er tildelt uden re-pairing." -ForegroundColor Green
    }
    "Revoke" {
        Set-ReadGrantTransition -Transition revoke -RequestedDeviceId $DeviceId
        Write-Host "agent4:read er fjernet; næste Pixel-request skal være 403." -ForegroundColor Yellow
    }
    "Regrant" {
        Set-ReadGrantTransition -Transition regrant -RequestedDeviceId $DeviceId
        Write-Host "agent4:read er tildelt igen uden re-pairing." -ForegroundColor Green
    }
    "RestartWorker" {
        $state = Read-OperatorState
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Assert-StatePhase -State $state -Allowed @("enabled_no_grant", "granted", "revoked", "regranted")
        Restart-ExpectedProcess -Kind worker -State $state
    }
    "RestartBackend" {
        $state = Read-OperatorState
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Assert-StatePhase -State $state -Allowed @("enabled_no_grant", "granted", "revoked", "regranted")
        Restart-ExpectedProcess -Kind backend -State $state
    }
    "MutateCampaignSnapshot" {
        $state = Read-OperatorState
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Assert-StatePhase -State $state -Allowed @("granted")
        Assert-CheckpointsPassed -Names @("grant_same_token_200")
        $receipt = Invoke-PhysicalFixtureMutation -Mode campaign-record -State $state
        Write-Host "Campaign-snapshot muteret: $receipt" -ForegroundColor Yellow
    }
    "MutateSummarySnapshot" {
        $state = Read-OperatorState
        Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
        Assert-StatePhase -State $state -Allowed @("granted")
        Assert-CheckpointsPassed -Names @("stale_campaign_record_422")
        $receipt = Invoke-PhysicalFixtureMutation -Mode summary -State $state
        Write-Host "Summary-snapshot muteret: $receipt" -ForegroundColor Yellow
    }
    "Stop" {
        $cleanup = Stop-RecordedStack
        if (Test-Path -LiteralPath $script:statePath -PathType Leaf) {
            $state = Read-OperatorState
            $state.phase = "stopped"
            $state.backend_pid = 0
            $state.worker_pid = 0
            Write-OperatorState -State $state
        }
        $cleanup | ConvertTo-Json -Depth 6
    }
    "Status" { Show-PhysicalStatus }
}
