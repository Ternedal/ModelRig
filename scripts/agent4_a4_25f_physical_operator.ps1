[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("Prepare", "DeviceInfo", "Grant", "RunMatrix", "Status", "Stop")]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedSha,
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [string]$LanAddress,
    [string]$Serial,
    [switch]$Replace
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$packageName = "dk.ternedal.modelrig.a425f"
$deviceInfoActivity = "dk.ternedal.modelrig.debug.Agent4PhysicalDeviceInfoActivity"
$snapshotProbeActivity = "dk.ternedal.modelrig.debug.Agent4SnapshotPhysicalProbeActivity"
$failureProbeActivity = "dk.ternedal.modelrig.debug.Agent4PhysicalFailureProbeActivity"
$workerPort = 18099
$lanPort = 18080
$adminPort = 18081
$firewallRule = "ModelRig A4-25f isolated Pixel read"
$fixtureScript = Join-Path $PSScriptRoot "agent4_a4_25f_physical_fixture.py"
$mutateScript = Join-Path $PSScriptRoot "agent4_a4_25f_physical_mutate.py"
$hostScript = Join-Path $PSScriptRoot "agent4_a4_25f_physical_host.py"

function Assert-WindowsAdministrator {
    if ($env:OS -ne "Windows_NT") { throw "A4-25f operatoren må kun køres på Windows-riggen." }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Kør PowerShell som administrator; A4-25f skal styre en snæver firewallregel."
    }
}

function Assert-Tool {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name blev ikke fundet på PATH."
    }
}

function Get-ExactHead {
    $value = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $value -notmatch "^[0-9a-f]{40}$") {
        throw "Kunne ikke læse en gyldig repository HEAD."
    }
    return $value
}

function Assert-ExactCleanHead {
    if ($ExpectedSha -notmatch "^[0-9a-f]{40}$") { throw "ExpectedSha skal være 40 lowercase hex." }
    $head = Get-ExactHead
    if ($head -ne $ExpectedSha) { throw "Forkert checkout: forventede $ExpectedSha, fik $head." }
    $dirty = @(& git -C $repoRoot status --porcelain)
    if ($LASTEXITCODE -ne 0) { throw "Kunne ikke kontrollere working tree." }
    if ($dirty.Count -ne 0) { throw "A4-25f kræver exact clean head; working tree er ikke ren." }
}

function Resolve-ExternalOutputRoot {
    # ROOTED-TJEKKET SKAL KOMME FOERST. Foer laa Join-Path-linjen UBETINGET
    # foerst, saa en ABSOLUT -OutputRoot blev sammensat med den aktuelle mappe:
    #   Join-Path "C:\...\ModelRig-git" "C:\Users\admin\a4-evidens"
    #     -> "C:\...\ModelRig-git\C:\Users\admin\a4-evidens"
    # -- en sti med kolon i midten, som GetFullPath afviser med
    # "Den angivne stis format understoettes ikke".
    #
    # Jo mere korrekt en absolut sti man sendte, desto sikrere kastede den.
    # 20/8 kostede det tre forsoeg, hvor jeg rettede output-roden og
    # LAN-adressen -- begge dele var i orden; det var sammensaetningen her.
    if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
        throw "A4-25f kraever -OutputRoot med en sti uden for repositoryet."
    }
    if ([IO.Path]::IsPathRooted($OutputRoot)) {
        $full = [IO.Path]::GetFullPath($OutputRoot)
    } else {
        $full = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $OutputRoot))
    }
    $repoPrefix = [IO.Path]::GetFullPath($repoRoot).TrimEnd('\') + '\'
    if ($full.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        [string]::Equals($full.TrimEnd('\'), [IO.Path]::GetFullPath($repoRoot).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "A4-25f output må ikke ligge i repositoryet."
    }
    if ([string]::Equals($full, [IO.Path]::GetPathRoot($full), [StringComparison]::OrdinalIgnoreCase)) {
        throw "A4-25f output må ikke være filesystem-roden."
    }
    return $full.TrimEnd('\')
}

$output = Resolve-ExternalOutputRoot
$statePath = Join-Path $output "a4-25f-operator-state.json"
$phoneReceipts = Join-Path $output "phone-receipts"
$binDir = Join-Path $output "bin"
$logsDir = Join-Path $output "logs"
$backendData = Join-Path $output "backend-device-store.json"
$fixtureData = Join-Path $output "fixture-data"
$fixtureManifest = Join-Path $output "fixture-manifest.json"
$backendExe = Join-Path $binDir "modelrig-a4-25f-backend.exe"
$grantExe = Join-Path $binDir "modelrig-agent4-grants.exe"

function Read-State {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw "A4-25f state mangler. Kør Prepare først."
    }
    return Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
}

function Write-State {
    param([Parameter(Mandatory = $true)]$State)
    $State.updated_at = (Get-Date).ToUniversalTime().ToString("o")
    $State | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Assert-StatePhase {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)][string[]]$Allowed)
    if ($Allowed -notcontains [string]$State.phase) {
        throw "A4-25f handlingen er ikke tilladt i fase '$($State.phase)'; forventede $($Allowed -join ', ')."
    }
}

function New-EphemeralAdminKey {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

function Test-PrivateIPv4 {
    param([Parameter(Mandatory = $true)][string]$Address)
    $ip = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$ip) -or $null -eq $ip -or $null -eq $ip.To4()) { return $false }
    $b = $ip.GetAddressBytes()
    return ($b[0] -eq 10) -or ($b[0] -eq 192 -and $b[1] -eq 168) -or ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31)
}

function Assert-PrivateLocalLanAddress {
    param([Parameter(Mandatory = $true)][string]$Address)
    if (-not (Test-PrivateIPv4 -Address $Address)) { throw "LanAddress skal være én konkret RFC1918 IPv4-adresse." }
    $ip = Get-NetIPAddress -AddressFamily IPv4 -IPAddress $Address -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $ip) { throw "LanAddress $Address findes ikke på riggen." }
    $profile = Get-NetConnectionProfile -InterfaceIndex ([int]$ip.InterfaceIndex) -ErrorAction Stop | Select-Object -First 1
    if ($null -eq $profile -or [string]$profile.NetworkCategory -ne "Private") {
        throw "A4-25f kræver Windows-netværksprofil Private."
    }
}

function Resolve-AdbSerial {
    Assert-Tool -Name "adb"
    if (-not [string]::IsNullOrWhiteSpace($Serial)) {
        if ($Serial -notmatch "^[A-Za-z0-9._:-]{1,128}$") { throw "Ugyldigt adb-serial." }
        $lines = @(& adb devices)
        if ($LASTEXITCODE -ne 0 -or -not ($lines | Where-Object { $_ -match "^$([regex]::Escape($Serial))\s+device$" })) {
            throw "ADB-enheden '$Serial' er ikke online som device."
        }
        return $Serial
    }
    $devices = @(& adb devices | Where-Object { $_ -match "^\S+\s+device$" } | ForEach-Object { ($_ -split "\s+")[0] })
    if ($LASTEXITCODE -ne 0) { throw "adb devices fejlede." }
    if ($devices.Count -ne 1) { throw "Der skal være præcis én online adb-enhed, eller angiv -Serial; fandt $($devices.Count)." }
    return [string]$devices[0]
}

function Invoke-Adb {
    param([Parameter(Mandatory = $true)][string]$DeviceSerial, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    # adb skriver rutinemaessigt til STDERR -- daemon-start, "device unauthorized",
    # fremdrift. Med $ErrorActionPreference='Stop' og 2>&1 bliver de linjer til
    # ErrorRecords i Windows PowerShell og udloeser NativeCommandError SELV naar
    # adb returnerer 0. Praecis den fejl draebte beviskampagnen 18/8 (#631).
    # Preferencen saenkes derfor omkring kaldet, og ErrorRecords flades til tekst.
    # EXITKODEN er verdiktet, ikke stderr.
    $_eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $outputLines = @(& adb -s $DeviceSerial @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ }
        })
    } finally { $ErrorActionPreference = $_eap }
    if ($LASTEXITCODE -ne 0) { throw "adb fejlede: $($outputLines -join ' ')" }
    return $outputLines
}

function Resolve-PixelPrivateIp {
    param([Parameter(Mandatory = $true)][string]$DeviceSerial, [Parameter(Mandatory = $true)][string]$TargetAddress)
    $route = (Invoke-Adb -DeviceSerial $DeviceSerial shell ip route get $TargetAddress) -join " "
    $match = [regex]::Match($route, "\bsrc\s+(\d+\.\d+\.\d+\.\d+)\b")
    if (-not $match.Success) { throw "Kunne ikke udlede Pixelens LAN-IP fra adb route." }
    $value = $match.Groups[1].Value
    if (-not (Test-PrivateIPv4 -Address $value)) { throw "Pixelens route-IP er ikke privat: $value" }
    return $value
}

function Remove-A4FirewallRule {
    Get-NetFirewallRule -DisplayName $firewallRule -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

function Install-A4FirewallRule {
    param([Parameter(Mandatory = $true)][string]$Address, [Parameter(Mandatory = $true)][string]$PixelIp)
    Remove-A4FirewallRule
    $rule = @{
        DisplayName = $firewallRule
        Direction = "Inbound"
        Action = "Allow"
        Program = $backendExe
        Protocol = "TCP"
        LocalAddress = $Address
        LocalPort = $lanPort
        RemoteAddress = $PixelIp
        Profile = "Private"
    }
    New-NetFirewallRule @rule | Out-Null
}

function Wait-Http200 {
    param([Parameter(Mandatory = $true)][string]$Url, [int]$Seconds = 60)
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ([int]$response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Endpoint blev ikke klar: $Url"
}

function Quote-ProcessArgument {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value -match '[\r\n"]') { throw "Procesargument indeholder ugyldige tegn." }
    return '"' + $Value + '"'
}

function Stop-RecordedProcess {
    param([int]$ProcessId, [ValidateSet("backend", "worker")][string]$Kind)
    if ($ProcessId -le 0) { return }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $process) { return }
    if ($Kind -eq "backend") {
        $actual = [string]$process.ExecutablePath
        if ([string]::IsNullOrWhiteSpace($actual) -or -not [string]::Equals([IO.Path]::GetFullPath($actual), [IO.Path]::GetFullPath($backendExe), [StringComparison]::OrdinalIgnoreCase)) {
            throw "Recorded backend PID tilhører ikke A4-25f-executable; processen bevares."
        }
    } else {
        $command = [string]$process.CommandLine
        if ($command -notmatch [regex]::Escape("agent4_a4_25f_physical_host.py") -or $command -notmatch [regex]::Escape($fixtureData)) {
            throw "Recorded worker PID matcher ikke A4-25f-host/data; processen bevares."
        }
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    Start-Sleep -Milliseconds 300
}

function Start-Worker {
    param([Parameter(Mandatory = $true)]$State, [int]$ClockOffsetMinutes = 0)
    if ([int]$State.worker_pid -gt 0) { Stop-RecordedProcess -ProcessId ([int]$State.worker_pid) -Kind worker }
    $python = (Get-Command python -ErrorAction Stop).Source
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmssfff")
    $outLog = Join-Path $logsDir "worker-$stamp.out.log"
    $errLog = Join-Path $logsDir "worker-$stamp.err.log"
    $args = @(
        (Quote-ProcessArgument $hostScript),
        "--data-root", (Quote-ProcessArgument $fixtureData),
        "--expected-sha", $ExpectedSha,
        "--host", "127.0.0.1",
        "--port", [string]$workerPort,
        "--clock-offset-minutes", [string]$ClockOffsetMinutes
    )
    $process = Start-Process -FilePath $python -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    $State.worker_pid = [int]$process.Id
    $State.worker_clock_offset_minutes = $ClockOffsetMinutes
    Write-State -State $State
    Wait-Http200 -Url "http://127.0.0.1:$workerPort/healthz"
}

function Start-Backend {
    param([Parameter(Mandatory = $true)]$State)
    if ([int]$State.backend_pid -gt 0) { Stop-RecordedProcess -ProcessId ([int]$State.backend_pid) -Kind backend }
    $key = New-EphemeralAdminKey
    $old = $env:MODELRIG_ADMIN_KEY
    $env:MODELRIG_ADMIN_KEY = $key
    try {
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmssfff")
        $outLog = Join-Path $logsDir "backend-$stamp.out.log"
        $errLog = Join-Path $logsDir "backend-$stamp.err.log"
        $args = @(
            "--lan-host", [string]$State.lan_address,
            "--lan-port", [string]$lanPort,
            "--admin-port", [string]$adminPort,
            "--worker-url", "http://127.0.0.1:$workerPort",
            "--data", (Quote-ProcessArgument $backendData)
        )
        $process = Start-Process -FilePath $backendExe -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    } finally {
        if ($null -eq $old) { Remove-Item Env:MODELRIG_ADMIN_KEY -ErrorAction SilentlyContinue }
        else { $env:MODELRIG_ADMIN_KEY = $old }
    }
    $State.backend_pid = [int]$process.Id
    Write-State -State $State
    Wait-Http200 -Url "http://127.0.0.1:$adminPort/healthz"
    return [pscustomobject]@{ State = $State; AdminKey = $key }
}

function Invoke-PythonFixture {
    param([switch]$ReplaceFixture)
    $python = (Get-Command python -ErrorAction Stop).Source
    $args = @($fixtureScript, "--output-root", $output, "--expected-sha", $ExpectedSha)
    if ($ReplaceFixture) { $args += "--replace" }
    & $python @args | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "A4-25f fixture-generator fejlede." }
}

function Invoke-Mutation {
    param([Parameter(Mandatory = $true)][ValidateSet("campaign-transition", "evidence-append", "campaign-add", "campaign-delete")][string]$Mode)
    $python = (Get-Command python -ErrorAction Stop).Source
    $lines = @(& $python $mutateScript --output-root $output --expected-sha $ExpectedSha --mode $Mode)
    if ($LASTEXITCODE -ne 0 -or $lines.Count -eq 0) { throw "A4-25f mutation '$Mode' fejlede." }
    return ($lines[-1] | ConvertFrom-Json)
}

function Build-PhysicalArtifacts {
    Assert-Tool -Name "go"
    Assert-Tool -Name "java"
    Assert-Tool -Name "adb"
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    Push-Location (Join-Path $repoRoot "backend")
    try {
        & go build -o $backendExe ./cmd/modelrig-a4-25f-backend
        if ($LASTEXITCODE -ne 0) { throw "A4-25f backend build fejlede." }
        & go build -o $grantExe ./cmd/modelrig-agent4-grants
        if ($LASTEXITCODE -ne 0) { throw "Agent4 grant CLI build fejlede." }
    } finally { Pop-Location }

    Push-Location (Join-Path $repoRoot "android")
    try {
        & .\gradlew.bat :app:assembleA425f --no-daemon --console=plain
        if ($LASTEXITCODE -ne 0) { throw "A425f APK build fejlede." }
    } finally { Pop-Location }
    $apks = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot "android\app\build\outputs\apk\a425f") -Filter "*.apk" -File -ErrorAction Stop)
    if ($apks.Count -ne 1) { throw "Forventede præcis én A425f APK; fandt $($apks.Count)." }
    return $apks[0].FullName
}

function Get-PhoneReceipt {
    param(
        [Parameter(Mandatory = $true)][string]$DeviceSerial,
        [Parameter(Mandatory = $true)][string]$ActivityClass,
        [string]$Stage,
        [Parameter(Mandatory = $true)][string]$FileName,
        [switch]$ForceStop
    )
    Invoke-Adb -DeviceSerial $DeviceSerial shell run-as $packageName rm -f "files/$FileName" | Out-Null
    if ($ForceStop) { Invoke-Adb -DeviceSerial $DeviceSerial shell am force-stop $packageName | Out-Null }
    $component = "$packageName/$ActivityClass"
    $arguments = @("shell", "am", "start", "-W", "-n", $component)
    if (-not [string]::IsNullOrWhiteSpace($Stage)) { $arguments += @("--es", "stage", $Stage) }
    Invoke-Adb -DeviceSerial $DeviceSerial @arguments | Out-Null
    $deadline = (Get-Date).AddSeconds(45)
    do {
        try {
            $raw = (Invoke-Adb -DeviceSerial $DeviceSerial shell run-as $packageName cat "files/$FileName") -join "`n"
            if (-not [string]::IsNullOrWhiteSpace($raw)) {
                $receipt = $raw | ConvertFrom-Json
                $target = Join-Path $phoneReceipts $FileName
                $raw | Set-Content -LiteralPath $target -Encoding UTF8
                if ($receipt.success -ne $true) { throw "Pixel-proben '$FileName' rapporterede fail-closed failure_type=$($receipt.failure_type)." }
                return $receipt
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Pixel-receipt blev ikke tilgængelig: $FileName"
}

function Invoke-SnapshotStage {
    param([string]$DeviceSerial, [string]$Stage, [switch]$ForceStop)
    return Get-PhoneReceipt -DeviceSerial $DeviceSerial -ActivityClass $snapshotProbeActivity -Stage $Stage -FileName "a4-25f-probe-$Stage.json" -ForceStop:$ForceStop
}

function Invoke-FailureStage {
    param([string]$DeviceSerial, [string]$Stage, [switch]$ForceStop)
    return Get-PhoneReceipt -DeviceSerial $DeviceSerial -ActivityClass $failureProbeActivity -Stage $Stage -FileName "a4-25f-failure-$Stage.json" -ForceStop:$ForceStop
}

function Read-FixtureManifest {
    if (-not (Test-Path -LiteralPath $fixtureManifest -PathType Leaf)) { throw "Fixture-manifest mangler." }
    return Get-Content -LiteralPath $fixtureManifest -Raw | ConvertFrom-Json
}

function Add-FirewallAndInstall {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)][string]$Apk)
    $deviceSerial = [string]$State.adb_serial
    Invoke-Adb -DeviceSerial $deviceSerial install -r $Apk | Out-Null
    $pixelIp = Resolve-PixelPrivateIp -DeviceSerial $deviceSerial -TargetAddress ([string]$State.lan_address)
    Install-A4FirewallRule -Address ([string]$State.lan_address) -PixelIp $pixelIp
    $State.pixel_ip = $pixelIp
    Write-State -State $State
}

function Show-State {
    $state = Read-State
    [ordered]@{
        schema = [string]$state.schema
        expected_sha = [string]$state.expected_sha
        phase = [string]$state.phase
        output_root = [string]$state.output_root
        lan_url = [string]$state.lan_url
        pixel_ip = [string]$state.pixel_ip
        adb_serial = [string]$state.adb_serial
        device_id = $state.device_id
        backend_pid = [int]$state.backend_pid
        worker_pid = [int]$state.worker_pid
        worker_clock_offset_minutes = [int]$state.worker_clock_offset_minutes
        apk_sha256 = [string]$state.apk_sha256
        matrix_receipt = $state.matrix_receipt
        public_network = $false
        production_activation = $false
    } | ConvertTo-Json -Depth 10
}

function Stop-A4Stack {
    param([Parameter(Mandatory = $true)]$State)
    if ([int]$State.backend_pid -gt 0) { Stop-RecordedProcess -ProcessId ([int]$State.backend_pid) -Kind backend }
    if ([int]$State.worker_pid -gt 0) { Stop-RecordedProcess -ProcessId ([int]$State.worker_pid) -Kind worker }
    Remove-A4FirewallRule
    try { Invoke-Adb -DeviceSerial ([string]$State.adb_serial) uninstall $packageName | Out-Null } catch { }
    Remove-Item -LiteralPath $backendData -Force -ErrorAction SilentlyContinue
    $State.backend_pid = 0
    $State.worker_pid = 0
    $State.phase = "stopped"
    Write-State -State $State
}

Assert-WindowsAdministrator
Assert-Tool -Name "git"
Assert-Tool -Name "python"
Assert-ExactCleanHead

switch ($Action) {
    "Prepare" {
        if ([string]::IsNullOrWhiteSpace($LanAddress)) { throw "Prepare kræver -LanAddress med riggens konkrete private IPv4." }
        Assert-PrivateLocalLanAddress -Address $LanAddress
        if (Test-Path -LiteralPath $statePath -PathType Leaf) {
            $existing = Read-State
            if (-not $Replace) { throw "A4-25f state findes allerede. Kør Stop eller brug bevidst -Replace." }
            try { Stop-A4Stack -State $existing } catch { Write-Warning $_.Exception.Message }
        }
        New-Item -ItemType Directory -Path $output -Force | Out-Null
        New-Item -ItemType Directory -Path $phoneReceipts -Force | Out-Null
        New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
        Invoke-PythonFixture -ReplaceFixture:$Replace
        $apk = Build-PhysicalArtifacts
        $deviceSerial = Resolve-AdbSerial
        $state = [pscustomobject][ordered]@{
            schema = "modelrig-agent4/a4-25f-operator-state/v1"
            created_at = (Get-Date).ToUniversalTime().ToString("o")
            updated_at = (Get-Date).ToUniversalTime().ToString("o")
            expected_sha = $ExpectedSha
            output_root = $output
            phase = "preparing"
            lan_address = $LanAddress
            lan_url = "http://${LanAddress}:$lanPort"
            pixel_ip = $null
            adb_serial = $deviceSerial
            package_name = $packageName
            apk = $apk
            apk_sha256 = "sha256:$((Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant())"
            backend_pid = 0
            worker_pid = 0
            worker_clock_offset_minutes = 0
            device_id = $null
            matrix_receipt = $null
            public_network = $false
            production_activation = $false
        }
        Write-State -State $state
        Add-FirewallAndInstall -State $state -Apk $apk
        $state = Read-State
        Start-Worker -State $state -ClockOffsetMinutes 0
        $state = Read-State
        $backend = Start-Backend -State $state
        $state = Read-State
        try {
            $pair = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$adminPort/api/v1/pair/start" -Headers @{ "X-Admin-Key" = $backend.AdminKey } -TimeoutSec 10
        } finally {
            $backend.AdminKey = $null
        }
        Invoke-Adb -DeviceSerial $deviceSerial shell monkey -p $packageName -c android.intent.category.LAUNCHER 1 | Out-Null
        $state.phase = "awaiting_pair"
        Write-State -State $state
        Write-Host "A4-25f isoleret stack er klar." -ForegroundColor Green
        Write-Host "A425f app: $packageName" -ForegroundColor Cyan
        Write-Host "Server-URL: $($state.lan_url)" -ForegroundColor Cyan
        Write-Host "Parringskode (gemmes ikke): $($pair.code)" -ForegroundColor Yellow
        Write-Host "Par A425f-appen manuelt, og kør derefter DeviceInfo." -ForegroundColor Yellow
    }
    "DeviceInfo" {
        $state = Read-State
        Assert-StatePhase -State $state -Allowed @("awaiting_pair", "paired_no_grant")
        $receipt = Get-PhoneReceipt -DeviceSerial ([string]$state.adb_serial) -ActivityClass $deviceInfoActivity -FileName "a4-25f-device-info.json"
        if ([string]::IsNullOrWhiteSpace([string]$receipt.device_id)) { throw "DeviceInfo manglede device_id." }
        $state.device_id = [string]$receipt.device_id
        $state.phase = "paired_no_grant"
        Write-State -State $state
        Write-Host "A425f-enhed identificeret uden at eksponere bearer-token." -ForegroundColor Green
    }
    "Grant" {
        $state = Read-State
        Assert-StatePhase -State $state -Allowed @("paired_no_grant")
        if ([string]::IsNullOrWhiteSpace([string]$state.device_id)) { throw "DeviceInfo skal køres før Grant." }
        $backend = Start-Backend -State $state
        $state = Read-State
        $old = $env:MODELRIG_ADMIN_KEY
        $env:MODELRIG_ADMIN_KEY = [string]$backend.AdminKey
        try {
            & $grantExe -grant ([string]$state.device_id) -url "http://127.0.0.1:$adminPort"
            if ($LASTEXITCODE -ne 0) { throw "Grant CLI afviste agent4:read." }
        } finally {
            if ($null -eq $old) { Remove-Item Env:MODELRIG_ADMIN_KEY -ErrorAction SilentlyContinue }
            else { $env:MODELRIG_ADMIN_KEY = $old }
            $backend.AdminKey = $null
        }
        $state.phase = "granted"
        Write-State -State $state
        Write-Host "agent4:read er tildelt den isolerede A425f-enhed." -ForegroundColor Green
    }
    "RunMatrix" {
        $state = Read-State
        Assert-StatePhase -State $state -Allowed @("granted", "matrix_complete")
        Stop-RecordedProcess -ProcessId ([int]$state.worker_pid) -Kind worker
        $state.worker_pid = 0
        Write-State -State $state
        Invoke-PythonFixture -ReplaceFixture
        Start-Worker -State $state -ClockOffsetMinutes 0
        $state = Read-State
        $baseline = Read-FixtureManifest
        $stageReceipts = New-Object System.Collections.Generic.List[object]
        $mutationReceipts = New-Object System.Collections.Generic.List[object]

        $listStart = Invoke-SnapshotStage -DeviceSerial ([string]$state.adb_serial) -Stage "list-start"
        $stageReceipts.Add($listStart)
        if ([string]$listStart.snapshot_id -ne [string]$baseline.root_snapshot_id) { throw "List baseline root matcher ikke fixture-manifest." }
        $mutationReceipts.Add((Invoke-Mutation -Mode "campaign-add"))
        $deleteReceipt = Invoke-Mutation -Mode "campaign-delete"
        if ([string]$deleteReceipt.mutation_id -ne "a4-25f-physical-030") { throw "Second-page delete-target driftede." }
        $mutationReceipts.Add($deleteReceipt)
        $listContinue = Invoke-SnapshotStage -DeviceSerial ([string]$state.adb_serial) -Stage "list-continue" -ForceStop
        $stageReceipts.Add($listContinue)
        if ([int]$listContinue.combined_count -ne 31 -or $listContinue.has_more -ne $false) { throw "Retained list continuation mistede/blandede campaigns." }
        if ([string]$listContinue.snapshot_id -ne [string]$baseline.root_snapshot_id) { throw "List continuation forlod baseline root." }

        $detail = Invoke-SnapshotStage -DeviceSerial ([string]$state.adb_serial) -Stage "detail-capture" -ForceStop
        $stageReceipts.Add($detail)
        $detailRoot = [string]$detail.snapshot_id
        $mutationReceipts.Add((Invoke-Mutation -Mode "campaign-transition"))
        $timelineStart = Invoke-SnapshotStage -DeviceSerial ([string]$state.adb_serial) -Stage "timeline-start" -ForceStop
        $stageReceipts.Add($timelineStart)
        if ([string]$timelineStart.snapshot_id -ne $detailRoot) { throw "Timeline-start forlod detail-rooten." }
        $mutationReceipts.Add((Invoke-Mutation -Mode "evidence-append"))

        $state = Read-State
        Start-Worker -State $state -ClockOffsetMinutes 0
        $state = Read-State
        $timelineContinue = Invoke-SnapshotStage -DeviceSerial ([string]$state.adb_serial) -Stage "timeline-continue" -ForceStop
        $stageReceipts.Add($timelineContinue)
        $evidenceStart = Invoke-SnapshotStage -DeviceSerial ([string]$state.adb_serial) -Stage "evidence-start" -ForceStop
        $stageReceipts.Add($evidenceStart)
        $mutationReceipts.Add((Invoke-Mutation -Mode "evidence-append"))

        $backend = Start-Backend -State $state
        $backend.AdminKey = $null
        $state = Read-State
        $evidenceContinue = Invoke-SnapshotStage -DeviceSerial ([string]$state.adb_serial) -Stage "evidence-continue" -ForceStop
        $stageReceipts.Add($evidenceContinue)
        $verify = Invoke-SnapshotStage -DeviceSerial ([string]$state.adb_serial) -Stage "verification" -ForceStop
        $stageReceipts.Add($verify)
        if ([string]$verify.snapshot_id -ne $detailRoot -or [string]$verify.a4_24_policy -ne "passed") { throw "Verification/A4-24-policy forlod retained detail-root." }

        $stageReceipts.Add((Invoke-FailureStage -DeviceSerial ([string]$state.adb_serial) -Stage "selected-root-404" -ForceStop))
        $stageReceipts.Add((Invoke-FailureStage -DeviceSerial ([string]$state.adb_serial) -Stage "server-422" -ForceStop))

        $currentPointer = Join-Path $fixtureData "operator-snapshots\current.json"
        $heldPointer = Join-Path $fixtureData "operator-snapshots\current.json.a4-25f-hold"
        if (Test-Path -LiteralPath $heldPointer) { throw "Stale A4-25f held current pointer findes allerede." }
        Move-Item -LiteralPath $currentPointer -Destination $heldPointer
        try {
            $stageReceipts.Add((Invoke-FailureStage -DeviceSerial ([string]$state.adb_serial) -Stage "current-unavailable-503" -ForceStop))
        } finally {
            if (Test-Path -LiteralPath $heldPointer) { Move-Item -LiteralPath $heldPointer -Destination $currentPointer }
        }

        $fresh = Invoke-SnapshotStage -DeviceSerial ([string]$state.adb_serial) -Stage "fresh-root" -ForceStop
        $stageReceipts.Add($fresh)
        if ([string]$fresh.snapshot_id -eq $detailRoot) { throw "Fresh flow observerede ikke den nye current root." }
        $stageReceipts.Add((Invoke-SnapshotStage -DeviceSerial ([string]$state.adb_serial) -Stage "unknown-root" -ForceStop))

        $state = Read-State
        Start-Worker -State $state -ClockOffsetMinutes 16
        $state = Read-State
        $expired = Invoke-FailureStage -DeviceSerial ([string]$state.adb_serial) -Stage "expired-retained-410" -ForceStop
        $stageReceipts.Add($expired)
        if ([int]$expired.http_status -ne 410) { throw "Retention clock-test gav ikke HTTP 410." }
        Start-Worker -State $state -ClockOffsetMinutes 0
        $state = Read-State

        $mutationFiles = @(Get-ChildItem -LiteralPath (Join-Path $output "mutations") -Filter "*.json" -File | Sort-Object Name)
        $phoneFiles = @(Get-ChildItem -LiteralPath $phoneReceipts -Filter "*.json" -File | Sort-Object Name)
        $shaAlgorithm = [Security.Cryptography.SHA256]::Create()
        try {
            $lanHashBytes = $shaAlgorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$state.lan_url))
        } finally { $shaAlgorithm.Dispose() }
        $matrix = [ordered]@{
            schema = "modelrig-agent4/a4-25f-physical-matrix/v1"
            recorded_at = (Get-Date).ToUniversalTime().ToString("o")
            repository_sha = $ExpectedSha
            apk_sha256 = [string]$state.apk_sha256
            package_name = $packageName
            pixel_ip = [string]$state.pixel_ip
            lan_url_sha256 = "sha256:$(([BitConverter]::ToString($lanHashBytes)).Replace('-', '').ToLowerInvariant())"
            baseline_root = [string]$baseline.root_snapshot_id
            retained_detail_root = $detailRoot
            final_current_root = [string]$fresh.snapshot_id
            stage_count = $stageReceipts.Count
            mutation_count = $mutationReceipts.Count
            mutation_receipts = @($mutationFiles | ForEach-Object { [ordered]@{ name = $_.Name; sha256 = "sha256:$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant())" } })
            phone_receipts = @($phoneFiles | ForEach-Object { [ordered]@{ name = $_.Name; sha256 = "sha256:$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant())" } })
            worker_restart_tested = $true
            backend_restart_tested = $true
            android_process_restart_tested = $true
            expired_retained_root_tested = $true
            selected_root_404_tested = $true
            server_422_tested = $true
            unavailable_503_tested = $true
            credential_in_receipt = $false
            raw_cursor_in_receipt = $false
            public_network = $false
            physical_execution = $true
            production_activation = $false
        }
        $matrixPath = Join-Path $output "a4-25f-physical-matrix.json"
        $matrix | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $matrixPath -Encoding UTF8
        $state.matrix_receipt = $matrixPath
        $state.phase = "matrix_complete"
        Write-State -State $state
        Write-Host "A4-25f fysisk matrix er kørt. Dette er stadig ikke human GO eller production activation." -ForegroundColor Green
    }
    "Status" { Show-State }
    "Stop" {
        $state = Read-State
        Stop-A4Stack -State $state
        Write-Host "A4-25f processer/firewall/isoleret APK/backend-store er ryddet; evidensfiler er bevaret." -ForegroundColor Green
    }
}
