[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [string]$ActionName,
    [Parameter(Mandatory = $true)][object[]]$ForwardArgs
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "agent4-physical-read-common.ps1")

$script:safetyPath = Join-Path $script:runtimeDir "safety-binding.json"
$script:safetyBlockRule = "ModelRig A4 safety transition block 8080"
$script:virtualInterfacePattern = "(?i)tailscale|vethernet|wsl|hyper-v|docker|loopback|vmware|virtualbox|npcap"

function Remove-SafetyTransitionBlock {
    Get-NetFirewallRule -DisplayName $script:safetyBlockRule -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

function Add-SafetyTransitionBlock {
    Remove-SafetyTransitionBlock
    New-NetFirewallRule `
        -DisplayName $script:safetyBlockRule `
        -Direction Inbound `
        -Action Block `
        -Protocol TCP `
        -LocalPort 8080 `
        -Profile Any | Out-Null
}

function Remove-LoopbackAdminBridge {
    & netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=8080 2>$null | Out-Null
}

function Invoke-WithLoopbackAdminBridge {
    param(
        [Parameter(Mandatory = $true)][string]$ConnectAddress,
        [Parameter(Mandatory = $true)][scriptblock]$Operation
    )
    if (-not (Test-PrivateIpv4Strict -Address $ConnectAddress)) {
        throw "Admin-bridge kræver en privat RFC1918-adresse."
    }
    Remove-LoopbackAdminBridge
    & netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=8080 connectaddress=$ConnectAddress connectport=8080 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Kunne ikke oprette den kortlivede lokale admin-bridge."
    }
    try {
        & $Operation
    }
    finally {
        Remove-LoopbackAdminBridge
    }
}

function Get-ArgumentValue {
    param(
        [Parameter(Mandatory = $true)][object[]]$Values,
        [Parameter(Mandatory = $true)][string]$Name
    )
    for ($index = 0; $index -lt $Values.Count; $index++) {
        if ([string]$Values[$index] -ieq $Name -and $index + 1 -lt $Values.Count) {
            return [string]$Values[$index + 1]
        }
    }
    return $null
}

function Get-ListenerRows {
    param([Parameter(Mandatory = $true)][int]$Port)
    return @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
            Sort-Object LocalAddress, OwningProcess
    )
}

function Assert-PortsFree {
    param([Parameter(Mandatory = $true)][string]$Context)
    $occupied = @()
    foreach ($port in @(8080, 8099)) {
        $rows = @(Get-ListenerRows -Port $port)
        if ($rows.Count -gt 0) {
            $occupied += "$port($($rows.Count))"
        }
    }
    if ($occupied.Count -gt 0) {
        throw "$Context: portene er ikke frie: $($occupied -join ', '). Ukendte processer bevares."
    }
}

function Test-PrivateIpv4Strict {
    param([Parameter(Mandatory = $true)][string]$Address)
    return (
        $Address -match "^10\." -or
        $Address -match "^192\.168\." -or
        $Address -match "^172\.(1[6-9]|2[0-9]|3[01])\."
    )
}

function Get-AdbValue {
    param(
        [Parameter(Mandatory = $true)][string]$Serial,
        [Parameter(Mandatory = $true)][string]$Property
    )
    $lines = @(& adb -s $Serial shell getprop $Property 2>$null)
    if ($LASTEXITCODE -ne 0) {
        throw "ADB kunne ikke læse $Property fra den bundne Pixel."
    }
    return (($lines -join "").Trim())
}

function Get-PhysicalPixel {
    param([string]$ExpectedSerial)
    Assert-Tool -Name adb
    $rows = @(
        & adb devices |
            Select-Object -Skip 1 |
            Where-Object { $_ -match "^\S+\s+device$" }
    )
    if ($LASTEXITCODE -ne 0) { throw "adb devices fejlede." }
    if ($rows.Count -ne 1) {
        throw "Præcis én autoriseret fysisk Google Pixel kræves; fandt $($rows.Count)."
    }
    $serial = (($rows[0] -split "\s+")[0]).Trim()
    if ($serial -match "^(?i)emulator-") {
        throw "A4-18 accepterer ikke en Android-emulator."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSerial) -and $serial -ne $ExpectedSerial) {
        throw "ADB-enheden skiftede under A4-18."
    }

    $kernelQemu = Get-AdbValue -Serial $serial -Property "ro.kernel.qemu"
    $bootQemu = Get-AdbValue -Serial $serial -Property "ro.boot.qemu"
    $manufacturer = Get-AdbValue -Serial $serial -Property "ro.product.manufacturer"
    $model = Get-AdbValue -Serial $serial -Property "ro.product.model"
    if ($kernelQemu -eq "1" -or $bootQemu -eq "1") {
        throw "A4-18 kræver fysisk hardware; QEMU/emulator blev fundet."
    }
    if ($manufacturer -ine "Google" -or $model -notmatch "^Pixel\b") {
        throw "A4-18 kræver en fysisk Google Pixel; fandt '$manufacturer $model'."
    }

    return [pscustomobject][ordered]@{
        serial = $serial
        serial_sha256 = "sha256:$(Get-Sha256HexForBytes -Bytes ([Text.Encoding]::UTF8.GetBytes($serial)))"
        manufacturer = $manufacturer
        model = $model
        android_release = Get-AdbValue -Serial $serial -Property "ro.build.version.release"
        sdk = Get-AdbValue -Serial $serial -Property "ro.build.version.sdk"
    }
}

function Read-SafetyBinding {
    if (-not (Test-Path -LiteralPath $script:safetyPath -PathType Leaf)) {
        throw "A4-18 safety-binding mangler. Start forfra med PrepareOff på exact head."
    }
    return Get-Content -LiteralPath $script:safetyPath -Raw | ConvertFrom-Json
}

function Assert-SamePhysicalPixel {
    $binding = Read-SafetyBinding
    $pixel = Get-PhysicalPixel -ExpectedSerial ([string]$binding.adb_serial)
    if (
        [string]$pixel.manufacturer -ne [string]$binding.pixel_manufacturer -or
        [string]$pixel.model -ne [string]$binding.pixel_model
    ) {
        throw "Pixel-identiteten ændrede sig under A4-18."
    }
    return $pixel
}

function Resolve-StrictLanBinding {
    param([Parameter(Mandatory = $true)][string]$Address)

    if (-not (Test-PrivateIpv4Strict -Address $Address)) {
        throw "A4-18 afviser ikke-private eller wildcard backend-adresser: $Address"
    }
    $matches = @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                [string]$_.IPAddress -eq $Address -and
                $_.AddressState -eq "Preferred" -and
                [string]$_.InterfaceAlias -notmatch $script:virtualInterfacePattern
            }
    )
    if ($matches.Count -ne 1) {
        throw "LAN-adressen $Address er ikke entydigt bundet til en aktiv ikke-virtuel interface."
    }
    $selected = $matches[0]
    $profile = Get-NetConnectionProfile -InterfaceIndex ([int]$selected.InterfaceIndex) -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $profile -or [string]$profile.NetworkCategory -eq "Public") {
        throw "A4-18 afviser Public eller ukendt netværksprofil."
    }
    return [pscustomobject][ordered]@{
        address = $Address
        interface_alias = [string]$selected.InterfaceAlias
        interface_index = [int]$selected.InterfaceIndex
        profile = [string]$profile.NetworkCategory
    }
}

function Stop-StackBeforeTransition {
    param(
        [Parameter(Mandatory = $true)][string]$Context,
        [switch]$PreserveAdminKey
    )
    if (Test-Path -LiteralPath $script:statePath -PathType Leaf) {
        $cleanup = Stop-RecordedStack -PreserveAdminKey:$PreserveAdminKey
        if (
            [bool]$cleanup.unknown_process_preserved -or
            -not [bool]$cleanup.firewall_removed
        ) {
            throw "$Context: den tidligere stack kunne ikke ryddes sikkert."
        }
    }
    else {
        Remove-TestFirewall
    }
    Assert-PortsFree -Context $Context
}

function Test-ExpectedBackend {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Address
    )
    $rows = @(Get-ListenerRows -Port 8080)
    return (
        $rows.Count -eq 1 -and
        [int]$rows[0].OwningProcess -eq $ProcessId -and
        [string]$rows[0].LocalAddress -eq $Address -and
        (Test-ExpectedProcess -ProcessId $ProcessId -Kind backend)
    )
}

function Test-ExpectedWorker {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    $rows = @(Get-ListenerRows -Port 8099)
    return (
        $rows.Count -eq 1 -and
        [int]$rows[0].OwningProcess -eq $ProcessId -and
        [string]$rows[0].LocalAddress -eq "127.0.0.1" -and
        (Test-ExpectedProcess -ProcessId $ProcessId -Kind worker)
    )
}

function Harden-RunningStack {
    param([Parameter(Mandatory = $true)]$Pixel)

    $state = Read-OperatorState
    Assert-ExactCleanHead -RequiredSha ([string]$state.expected_sha)
    $uri = [Uri]([string]$state.lan_url)
    $lan = Resolve-StrictLanBinding -Address ([string]$uri.Host)

    $backendPid = [int]$state.backend_pid
    if (-not (Stop-ExpectedListener -Kind backend -RecordedPid $backendPid -Port 8080)) {
        throw "Safety-gaten kunne ikke stoppe den wildcard-bundne backend sikkert."
    }

    $command = Get-Content -LiteralPath $script:backendCmd -Raw
    $unsafe = 'set "MODELRIG_HOST=0.0.0.0"'
    $safe = 'set "MODELRIG_HOST=' + $lan.address + '"'
    if ($command -notmatch [regex]::Escape($unsafe)) {
        throw "backend.cmd havde ikke den forventede wildcard-binding; hardening afbrudt."
    }
    $command = $command.Replace($unsafe, $safe)
    $command | Set-Content -LiteralPath $script:backendCmd -Encoding ASCII

    Remove-TestFirewall
    New-NetFirewallRule `
        -DisplayName $script:firewallRule `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalAddress $lan.address `
        -LocalPort 8080 `
        -RemoteAddress LocalSubnet `
        -Profile Private,Domain | Out-Null
    Remove-SafetyTransitionBlock

    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", ('"' + $script:backendCmd + '"') -WorkingDirectory $script:runtimeDir | Out-Null
    Wait-Endpoint -Url "$($state.lan_url)/healthz"
    $newBackendPid = Get-ListenerPid -Port 8080
    if ($null -eq $newBackendPid -or -not (Test-ExpectedBackend -ProcessId $newBackendPid -Address $lan.address)) {
        [void](Stop-CurrentExpectedListeners)
        throw "Backend blev ikke verificeret på den eksakte private LAN-adresse."
    }
    $workerPid = Get-ListenerPid -Port 8099
    if ($null -eq $workerPid -or -not (Test-ExpectedWorker -ProcessId $workerPid)) {
        [void](Stop-CurrentExpectedListeners)
        throw "Worker blev ikke verificeret som ren loopback-listener."
    }

    $state.backend_pid = [int]$newBackendPid
    Write-OperatorState -State $state
    [ordered]@{
        schema = "modelrig-agent4/physical-read-safety-binding/v1"
        expected_sha = [string]$state.expected_sha
        recorded_at = (Get-Date).ToUniversalTime().ToString("o")
        adb_serial = [string]$Pixel.serial
        adb_serial_sha256 = [string]$Pixel.serial_sha256
        pixel_manufacturer = [string]$Pixel.manufacturer
        pixel_model = [string]$Pixel.model
        pixel_android_release = [string]$Pixel.android_release
        pixel_sdk = [string]$Pixel.sdk
        physical_pixel = $true
        lan_address = [string]$lan.address
        lan_interface_alias = [string]$lan.interface_alias
        lan_interface_index = [int]$lan.interface_index
        network_profile = [string]$lan.profile
        backend_bound_address = [string]$lan.address
        worker_bound_address = "127.0.0.1"
        firewall_local_address = [string]$lan.address
        firewall_remote_scope = "LocalSubnet"
        wildcard_binding = $false
        public_network = $false
        production_activation = $false
    } | ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath $script:safetyPath -Encoding UTF8
}

function Assert-RunningStackHardened {
    $binding = Read-SafetyBinding
    $state = Read-OperatorState
    Assert-ExactCleanHead -RequiredSha ([string]$binding.expected_sha)
    [void](Resolve-StrictLanBinding -Address ([string]$binding.lan_address))
    $backendPid = Get-ListenerPid -Port 8080
    $workerPid = Get-ListenerPid -Port 8099
    if (
        $null -eq $backendPid -or
        -not (Test-ExpectedBackend -ProcessId $backendPid -Address ([string]$binding.lan_address))
    ) {
        throw "Backend er ikke længere bundet til den godkendte private LAN-adresse."
    }
    if ($null -eq $workerPid -or -not (Test-ExpectedWorker -ProcessId $workerPid)) {
        throw "Worker er ikke længere bundet til loopback."
    }
    if ([int]$state.backend_pid -ne [int]$backendPid -or [int]$state.worker_pid -ne [int]$workerPid) {
        throw "Operator-state matcher ikke de verificerede listener-PID'er."
    }
}

function Patch-FinalReceipt {
    if (-not (Test-Path -LiteralPath $script:receiptPath -PathType Leaf)) { return }
    $binding = Read-SafetyBinding
    $receipt = Get-Content -LiteralPath $script:receiptPath -Raw | ConvertFrom-Json
    if ([string]$receipt.expected_sha -ne [string]$binding.expected_sha) {
        throw "Receipt og safety-binding har forskellig exact SHA."
    }

    $bindingReceipt = Get-FileReceipt -Path $script:safetyPath
    $hardening = [pscustomobject][ordered]@{
        schema = "modelrig-agent4/physical-read-safety-evidence/v1"
        physical_pixel = $true
        pixel_serial_sha256 = [string]$binding.adb_serial_sha256
        pixel_manufacturer = [string]$binding.pixel_manufacturer
        pixel_model = [string]$binding.pixel_model
        lan_address = [string]$binding.lan_address
        lan_interface_alias = [string]$binding.lan_interface_alias
        network_profile = [string]$binding.network_profile
        backend_bound_address = [string]$binding.backend_bound_address
        worker_bound_address = [string]$binding.worker_bound_address
        firewall_local_address = [string]$binding.firewall_local_address
        firewall_remote_scope = [string]$binding.firewall_remote_scope
        wildcard_binding = $false
        artifacts_hashed_after_prestop = $true
        binding_file = $bindingReceipt
        public_network = $false
        production_activation = $false
    }
    $receipt | Add-Member -NotePropertyName safety_hardening -NotePropertyValue $hardening -Force
    $receipt.PSObject.Properties.Remove("receipt_sha256")
    $withoutDigest = $receipt | ConvertTo-Json -Depth 40 -Compress
    $digest = "sha256:$(Get-Sha256HexForBytes -Bytes ([Text.Encoding]::UTF8.GetBytes($withoutDigest)))"
    $receipt | Add-Member -NotePropertyName receipt_sha256 -NotePropertyValue $digest -Force
    $receipt | ConvertTo-Json -Depth 40 |
        Set-Content -LiteralPath $script:receiptPath -Encoding UTF8
}

Assert-WindowsAdministrator
if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
    throw "A4-18 target mangler: $Target"
}

$action = if ([string]::IsNullOrWhiteSpace($ActionName)) { "" } else { $ActionName }
$targetError = $null

switch ($action) {
    "PrepareOff" {
        $expectedSha = Get-ArgumentValue -Values $ForwardArgs -Name "-ExpectedSha"
        if ([string]::IsNullOrWhiteSpace($expectedSha)) {
            throw "Safety-gaten kræver exact -ExpectedSha."
        }
        Assert-ExactCleanHead -RequiredSha $expectedSha
        $pixel = Get-PhysicalPixel
        Stop-StackBeforeTransition -Context "PrepareOff"
        Add-SafetyTransitionBlock
        try {
            & $Target @ForwardArgs
            if (-not $?) { throw "PrepareOff target fejlede." }
            Harden-RunningStack -Pixel $pixel
        }
        catch {
            [void](Stop-CurrentExpectedListeners)
            throw
        }
        finally {
            Remove-SafetyTransitionBlock
        }
    }

    "Enable" {
        [void](Assert-SamePhysicalPixel)
        Stop-StackBeforeTransition -Context "Enable" -PreserveAdminKey
        Add-SafetyTransitionBlock
        try {
            & $Target @ForwardArgs
            if (-not $?) { throw "Enable target fejlede." }
            $pixel = Assert-SamePhysicalPixel
            Harden-RunningStack -Pixel $pixel
        }
        catch {
            [void](Stop-CurrentExpectedListeners)
            throw
        }
        finally {
            Remove-SafetyTransitionBlock
        }
    }

    "Grant" {
        [void](Assert-SamePhysicalPixel)
        Assert-RunningStackHardened
        $binding = Read-SafetyBinding
        Invoke-WithLoopbackAdminBridge -ConnectAddress ([string]$binding.lan_address) -Operation {
            & $Target @ForwardArgs
            if (-not $?) { throw "Grant target fejlede." }
        }
        Assert-RunningStackHardened
    }

    "Revoke" {
        [void](Assert-SamePhysicalPixel)
        Assert-RunningStackHardened
        $binding = Read-SafetyBinding
        Invoke-WithLoopbackAdminBridge -ConnectAddress ([string]$binding.lan_address) -Operation {
            & $Target @ForwardArgs
            if (-not $?) { throw "Revoke target fejlede." }
        }
        Assert-RunningStackHardened
    }

    "Regrant" {
        [void](Assert-SamePhysicalPixel)
        Assert-RunningStackHardened
        $binding = Read-SafetyBinding
        Invoke-WithLoopbackAdminBridge -ConnectAddress ([string]$binding.lan_address) -Operation {
            & $Target @ForwardArgs
            if (-not $?) { throw "Regrant target fejlede." }
        }
        Assert-RunningStackHardened
    }

    "RestartBackend" {
        Assert-RunningStackHardened
        & $Target @ForwardArgs
        if (-not $?) { throw "RestartBackend target fejlede." }
        Assert-RunningStackHardened
    }

    "RestartWorker" {
        Assert-RunningStackHardened
        & $Target @ForwardArgs
        if (-not $?) { throw "RestartWorker target fejlede." }
        Assert-RunningStackHardened
    }

    "MutateCampaignSnapshot" {
        Assert-RunningStackHardened
        & $Target @ForwardArgs
        if (-not $?) { throw "Campaign-mutation target fejlede." }
        Assert-RunningStackHardened
    }

    "MutateSummarySnapshot" {
        Assert-RunningStackHardened
        & $Target @ForwardArgs
        if (-not $?) { throw "Summary-mutation target fejlede." }
        Assert-RunningStackHardened
    }

    "Finalize" {
        [void](Assert-SamePhysicalPixel)
        Assert-RunningStackHardened
        Stop-StackBeforeTransition -Context "Finalize pre-stop"
        try {
            & $Target @ForwardArgs
            if (-not $?) { throw "Finalize target fejlede." }
        }
        catch {
            $targetError = $_
        }
        finally {
            Remove-LoopbackAdminBridge
            Remove-SafetyTransitionBlock
            Patch-FinalReceipt
        }
        if ($null -ne $targetError) { throw $targetError }
    }

    "Stop" {
        try {
            & $Target @ForwardArgs
            if (-not $?) { throw "Stop target fejlede." }
        }
        finally {
            Remove-LoopbackAdminBridge
            Remove-SafetyTransitionBlock
            Remove-TestFirewall
        }
        Assert-PortsFree -Context "Stop"
    }

    "Record" {
        & $Target @ForwardArgs
        if (-not $?) { throw "Record target fejlede." }
    }

    "Status" {
        & $Target @ForwardArgs
        if (-not $?) { throw "Status target fejlede." }
        if (Test-Path -LiteralPath $script:safetyPath -PathType Leaf) {
            $binding = Read-SafetyBinding
            [ordered]@{
                safety_expected_sha = [string]$binding.expected_sha
                physical_pixel = [bool]$binding.physical_pixel
                pixel_model = [string]$binding.pixel_model
                lan_address = [string]$binding.lan_address
                network_profile = [string]$binding.network_profile
                backend_bound_address = [string]$binding.backend_bound_address
                worker_bound_address = [string]$binding.worker_bound_address
                wildcard_binding = [bool]$binding.wildcard_binding
                public_network = $false
                production_activation = $false
            } | ConvertTo-Json -Depth 6
        }
    }

    default {
        & $Target @ForwardArgs
        if (-not $?) { throw "A4-18 target fejlede." }
    }
}
