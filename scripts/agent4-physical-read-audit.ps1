[CmdletBinding()]
param(
    [string]$ReceiptPath,
    [string]$RepoRoot,
    [string]$OutputPath,
    [switch]$RequireRemoteRefs,
    [switch]$SelfTest
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ExpectedBranch = "agent/a4-18-physical-read-product"
$IntegrationBase = "503d4a61b7d7742a34282eb35a1373f0ccacf023"
$FrozenMainAnchor = "218019fd47ea90b046a334253ab5fd84485f772a"
$ReceiptSchema = "modelrig-agent4/physical-read-receipt/v2"
$FixtureSchema = "modelrig-agent4/physical-read-fixture/v1"
$MutationSchema = "modelrig-agent4/physical-read-mutation/v1"
$ShaPattern = '^sha256:[0-9a-f]{64}$'
$Findings = New-Object System.Collections.ArrayList

function Add-Finding {
    param([ValidateSet("error", "warning", "info")][string]$Level, [string]$Code, [string]$Message)
    [void]$script:Findings.Add([ordered]@{ level = $Level; code = $Code; message = $Message })
}

function Get-Sha256ForBytes {
    param([byte[]]$Bytes)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $hash = $algorithm.ComputeHash($Bytes) }
    finally { $algorithm.Dispose() }
    return "sha256:$(([BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant())"
}

function Get-Sha256ForText {
    param([string]$Text)
    return Get-Sha256ForBytes -Bytes ([Text.Encoding]::UTF8.GetBytes($Text))
}

function Test-Sha256 {
    param($Value)
    return $Value -is [string] -and $Value -match $script:ShaPattern
}

function Get-PropertyValue {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-ObjectWithoutProperty {
    param($Object, [string]$ExcludedName)
    $copy = [ordered]@{}
    foreach ($property in $Object.PSObject.Properties) {
        if ($property.Name -ne $ExcludedName) { $copy[$property.Name] = $property.Value }
    }
    return $copy
}

function Test-SafeRelativePath {
    param($Value)
    if (-not ($Value -is [string]) -or [string]::IsNullOrWhiteSpace($Value)) { return $false }
    if ($Value.Contains('\') -or $Value.StartsWith('/') -or $Value -match '(^|/)\.\.(/|$)') { return $false }
    return $true
}

function Scan-Credentials {
    param($Value, [string]$Path = "root")
    $forbiddenKeys = @("authorization", "bearer", "bearer_token", "device_token", "token", "pairing_code", "admin_key", "modelrig_admin_key", "password", "secret", "client_secret", "private_key")
    if ($null -eq $Value) { return }
    if ($Value -is [string]) {
        foreach ($pattern in @('(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}', '(?i)MODELRIG_ADMIN_KEY\s*=', '(?i)\bpairing[_ -]?code\s*[:=]\s*\S+', '(?i)\bdevice[_ -]?token\s*[:=]\s*\S+')) {
            if ($Value -match $pattern) { Add-Finding error credential.value "Credential-lignende værdi ved $Path"; break }
        }
        return
    }
    if ($Value -is [System.Collections.IDictionary]) {
        foreach ($key in $Value.Keys) {
            $name = [string]$key
            if ($forbiddenKeys -contains $name.ToLowerInvariant()) { Add-Finding error credential.key "Forbudt felt: $Path.$name" }
            Scan-Credentials -Value $Value[$key] -Path "$Path.$name"
        }
        return
    }
    if ($Value -is [System.Collections.IEnumerable] -and -not ($Value -is [string])) {
        $index = 0
        foreach ($item in $Value) { Scan-Credentials -Value $item -Path "$Path[$index]"; $index++ }
        return
    }
    foreach ($property in $Value.PSObject.Properties) {
        if ($forbiddenKeys -contains $property.Name.ToLowerInvariant()) { Add-Finding error credential.key "Forbudt felt: $Path.$($property.Name)" }
        Scan-Credentials -Value $property.Value -Path "$Path.$($property.Name)"
    }
}

function Invoke-Git {
    param([string[]]$Arguments, [switch]$AllowFailure)
    $output = @(& git -C $script:RepoRootResolved @Arguments 2>&1)
    $code = $LASTEXITCODE
    if (-not $AllowFailure -and $code -ne 0) { throw "git $($Arguments -join ' ') fejlede: $($output -join ' ')" }
    return [pscustomobject]@{ Code = $code; Lines = $output; Text = ($output -join "`n").Trim() }
}

function Validate-MainDigest {
    param($Receipt)
    $claimed = Get-PropertyValue $Receipt "receipt_sha256"
    if (-not (Test-Sha256 $claimed)) { Add-Finding error digest.main.format "receipt_sha256 mangler eller er ugyldig"; return }
    $without = Get-ObjectWithoutProperty -Object $Receipt -ExcludedName "receipt_sha256"
    $compact = $without | ConvertTo-Json -Depth 30 -Compress
    $actual = Get-Sha256ForText $compact
    if ($actual -ne $claimed) { Add-Finding error digest.main.mismatch "Hovedreceiptens digest matcher ikke indholdet" }
    else { Add-Finding info digest.main.ok "Hovedreceiptens digest er gyldig" }
}

function Validate-Trials {
    param($Trials)
    $required = @(
        "default_off_feature_locked", "default_off_no_worker_fallback", "paired_without_grant_403",
        "paired_without_grant_locked_no_stale", "grant_same_token_200", "campaign_paging_no_loss",
        "timeline_paging_no_loss", "evidence_paging_no_loss", "detail_verification_matches",
        "no_write_controls", "stale_campaign_record_422", "stale_summary_422", "revoke_same_token_403",
        "revoke_clears_data", "restart_does_not_restore_grant", "regrant_same_token_200",
        "backend_restart_recovery", "worker_restart_recovery", "network_recovery",
        "malformed_schema_fail_closed", "not_found_fail_closed"
    )
    $http = @{
        default_off_feature_locked = 404; paired_without_grant_403 = 403; grant_same_token_200 = 200;
        stale_campaign_record_422 = 422; stale_summary_422 = 422; revoke_same_token_403 = 403;
        restart_does_not_restore_grant = 403; regrant_same_token_200 = 200; backend_restart_recovery = 200;
        worker_restart_recovery = 200; network_recovery = 200; malformed_schema_fail_closed = 200;
        not_found_fail_closed = 404
    }
    $payloadRequired = @("grant_same_token_200", "campaign_paging_no_loss", "timeline_paging_no_loss", "evidence_paging_no_loss", "detail_verification_matches")
    $cursorRequired = @("campaign_paging_no_loss", "timeline_paging_no_loss", "evidence_paging_no_loss", "stale_campaign_record_422", "stale_summary_422")
    foreach ($name in $required) {
        $entry = Get-PropertyValue $Trials $name
        if ($null -eq $entry) { Add-Finding error trials.missing "Manglende checkpoint: $name"; continue }
        if ([string](Get-PropertyValue $entry "status") -ne "pass") { Add-Finding error "trial.$name.status" "$name er ikke pass" }
        if ($http.ContainsKey($name) -and [int](Get-PropertyValue $entry "http_status") -ne [int]$http[$name]) { Add-Finding error "trial.$name.http" "$name har forkert HTTP-status" }
        $route = Get-PropertyValue $entry "route"
        if ($null -ne $route -and ((-not ([string]$route).StartsWith('/api/')) -or ([string]$route).Contains('?') -or ([string]$route).Contains('#'))) { Add-Finding error "trial.$name.route" "$name har en usikker route" }
        if ($payloadRequired -contains $name -and -not (Test-Sha256 (Get-PropertyValue $entry "payload_sha256"))) { Add-Finding error "trial.$name.payload" "$name mangler payload_sha256" }
        if ($cursorRequired -contains $name -and -not (Test-Sha256 (Get-PropertyValue $entry "cursor_sha256"))) { Add-Finding error "trial.$name.cursor" "$name mangler cursor_sha256" }
    }
}

function Validate-Fixture {
    param($Fixture)
    if ([string](Get-PropertyValue $Fixture "schema") -ne $script:FixtureSchema) { Add-Finding error fixture.schema "Forkert fixture-schema" }
    foreach ($name in @("campaign_count", "timeline_count", "evidence_count")) {
        if ([int](Get-PropertyValue $Fixture $name) -le 25) { Add-Finding error "fixture.$name" "$name krydser ikke sidegrænsen" }
    }
    if ([int](Get-PropertyValue $Fixture "evidence_count") -ne [int](Get-PropertyValue $Fixture "evidence_verification_count")) { Add-Finding error fixture.counts "Evidence counts er inkonsistente" }
    if ([string](Get-PropertyValue $Fixture "selected_campaign_id") -ne "a4-18-physical-primary") { Add-Finding error fixture.campaign "Forkert selected campaign" }
    foreach ($name in @("latest_timeline_hash", "evidence_head_hash", "first_payload_sha256", "last_payload_sha256")) {
        if (-not (Test-Sha256 (Get-PropertyValue $Fixture $name))) { Add-Finding error "fixture.$name" "$name er ugyldig" }
    }
    foreach ($name in @("external_dispatch", "background_runtime", "production_activation")) {
        if ((Get-PropertyValue $Fixture $name) -ne $false) { Add-Finding error "fixture.$name" "$name skal være false" }
    }
}

function Validate-Mutations {
    param($Mutations)
    $items = @($Mutations)
    if ($items.Count -ne 2) { Add-Finding error mutations.count "Der skal være præcis to mutationer"; return }
    $modes = @()
    foreach ($item in $items) {
        if ([string](Get-PropertyValue $item "schema") -ne $script:MutationSchema) { Add-Finding error mutation.schema "Forkert mutation-schema" }
        $mode = [string](Get-PropertyValue $item "mode"); $modes += $mode
        foreach ($name in @("external_dispatch", "background_runtime", "production_activation")) { if ((Get-PropertyValue $item $name) -ne $false) { Add-Finding error "mutation.$mode.$name" "$name skal være false" } }
        if (-not (Test-Sha256 (Get-PropertyValue $item "receipt_sha256"))) { Add-Finding error "mutation.$mode.digest" "Mutation digest er ugyldig" }
        $cb = [int](Get-PropertyValue $item "campaign_count_before"); $ca = [int](Get-PropertyValue $item "campaign_count_after")
        $eb = [int](Get-PropertyValue $item "evidence_count_before"); $ea = [int](Get-PropertyValue $item "evidence_count_after")
        $tb = [string](Get-PropertyValue $item "timeline_head_before"); $ta = [string](Get-PropertyValue $item "timeline_head_after")
        $hb = [string](Get-PropertyValue $item "evidence_head_before"); $ha = [string](Get-PropertyValue $item "evidence_head_after")
        if ($mode -eq "campaign-record" -and ($ca -ne $cb + 1 -or $ea -ne $eb -or $tb -ne $ta -or $hb -ne $ha)) { Add-Finding error mutation.campaign.effect "Campaign-mutationen har forkert effekt" }
        if ($mode -eq "summary" -and ($ca -ne $cb -or $ea -ne $eb + 1 -or $tb -eq $ta -or $hb -eq $ha)) { Add-Finding error mutation.summary.effect "Summary-mutationen har forkert effekt" }
    }
    if (-not ($modes -contains "campaign-record") -or -not ($modes -contains "summary")) { Add-Finding error mutations.modes "Mutation modes er ufuldstændige" }
}

function Validate-Artifacts {
    param($Artifacts)
    $critical = @(
        "validation/agent4-physical-runtime/fixture-manifest.json", "validation/agent4-physical-runtime/backend.log",
        "validation/agent4-physical-runtime/worker.log", "validation/agent4-physical-runtime/modelrig-data.json",
        "validation/agent4-physical-runtime/modelrig-server-a4-physical.exe",
        "validation/agent4-physical-runtime/modelrig-agent4-grants-a4-physical.exe",
        "worker/app/entrypoint.py", "worker/app/agent4/production_bootstrap.py", "worker/app/agent4/operator_api.py",
        "worker/app/agent4/campaign_list_query.py", "android/app/src/main/java/dk/ternedal/modelrig/net/Agent4OperatorClient.kt",
        "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent4OperatorScreen.kt",
        "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent4CampaignDetailScreen.kt"
    )
    $paths = @(); $seen = @{}
    foreach ($entry in @($Artifacts)) {
        $path = [string](Get-PropertyValue $entry "path")
        if (-not (Test-SafeRelativePath $path)) { Add-Finding error artifacts.path "Usikker artifact-path: $path"; continue }
        if ($seen.ContainsKey($path)) { Add-Finding error artifacts.duplicate "Dublet artifact: $path" } else { $seen[$path] = $true }
        $paths += $path
        $file = Join-Path $script:RepoRootResolved ($path.Replace('/', '\'))
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { Add-Finding error artifacts.missing "Artifact mangler: $path"; continue }
        if ([int64](Get-PropertyValue $entry "size_bytes") -ne (Get-Item -LiteralPath $file).Length) { Add-Finding error artifacts.size "Artifact-størrelse afviger: $path" }
        $actual = "sha256:$((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant())"
        if ($actual -ne [string](Get-PropertyValue $entry "sha256")) { Add-Finding error artifacts.hash "Artifact-hash afviger: $path" }
    }
    foreach ($suffix in $critical) { if (-not ($paths | Where-Object { $_.EndsWith($suffix) })) { Add-Finding error artifacts.critical "Kritisk artifact mangler: $suffix" } }
    if (-not ($paths | Where-Object { $_.EndsWith("android/app/build/outputs/apk/debug/app-debug.apk") })) { Add-Finding error artifacts.apk "APK mangler i artifact-listen" }
}

function Validate-Git {
    $head = (Invoke-Git @("rev-parse", "HEAD")).Text.ToLowerInvariant()
    $branch = (Invoke-Git @("branch", "--show-current")).Text
    $script:ExpectedSha = $head
    if ($branch -ne $script:ExpectedBranch) { Add-Finding error git.branch "Forkert local branch: $branch" }
    if ((Invoke-Git @("merge-base", "--is-ancestor", $script:IntegrationBase, "HEAD") -AllowFailure).Code -ne 0) { Add-Finding error git.integration "Integrationsbase er ikke ancestor" }
    foreach ($line in (Invoke-Git @("status", "--porcelain", "--untracked-files=all")).Lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $path = if ($line.Length -ge 4) { $line.Substring(3).Trim().Replace('\', '/') } else { $line }
        if ($path.Contains(' -> ')) { $path = $path.Split(@(' -> '), 2, [StringSplitOptions]::None)[1] }
        if (-not $path.StartsWith('validation/')) { Add-Finding error git.dirty "Ikke-validation ændring: $line" }
    }
    if ($RequireRemoteRefs) {
        foreach ($item in @(
            @{ Ref = "refs/heads/main"; Expected = $script:FrozenMainAnchor; Code = "git.remote_main" },
            @{ Ref = "refs/heads/$($script:ExpectedBranch)"; Expected = $head; Code = "git.remote_head" }
        )) {
            $remote = Invoke-Git @("ls-remote", "--exit-code", "origin", $item.Ref) -AllowFailure
            $observed = if ($remote.Code -eq 0 -and $remote.Text) { $remote.Text.Split()[0] } else { "" }
            if ($observed -ne $item.Expected) { Add-Finding error $item.Code "Remote $($item.Ref) matcher ikke expected ref" }
        }
    }
    return $head
}

if ($SelfTest) {
    $value = [ordered]@{ a = 1; production_activation = $false }
    $digest = Get-Sha256ForText (($value | ConvertTo-Json -Compress))
    if (-not (Test-Sha256 $digest)) { throw "Self-test digest fejlede" }
    Scan-Credentials -Value ([ordered]@{ note = "safe" })
    if (@($Findings | Where-Object { $_.level -eq "error" }).Count -ne 0) { throw "Self-test credential scan fejlede" }
    Write-Host "A4-18 receipt auditor self-test: PASS" -ForegroundColor Green
    exit 0
}

try {
    if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path }
    $script:RepoRootResolved = (Resolve-Path $RepoRoot).Path
    if ([string]::IsNullOrWhiteSpace($ReceiptPath)) { $ReceiptPath = Join-Path $RepoRootResolved "validation\agent4-physical-read-latest.json" }
    if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) { throw "Receipt mangler: $ReceiptPath" }
    if ([string]::IsNullOrWhiteSpace($OutputPath)) { $OutputPath = Join-Path $env:USERPROFILE "ModelRig-Validation\A4-18-receipt-audit\receipt-audit-latest.json" }
    $receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $head = Validate-Git
    $version = (Get-Content -LiteralPath (Join-Path $RepoRootResolved "VERSION") -Raw).Trim()
    Scan-Credentials $receipt
    if ([string](Get-PropertyValue $receipt "schema") -ne $ReceiptSchema) { Add-Finding error receipt.schema "Forkert receipt-schema" }
    if ([string](Get-PropertyValue $receipt "expected_sha") -ne $head -or [string](Get-PropertyValue $receipt "observed_head") -ne $head) { Add-Finding error receipt.sha "Receipt matcher ikke exact local/remote head" }
    if ([string](Get-PropertyValue $receipt "branch") -ne $ExpectedBranch) { Add-Finding error receipt.branch "Forkert receipt-branch" }
    foreach ($name in @("backend_version", "worker_version")) { if ([string](Get-PropertyValue $receipt $name) -ne $version) { Add-Finding error "receipt.$name" "$name matcher ikke VERSION" } }
    if ([string](Get-PropertyValue $receipt "human_decision") -ne "GO") { Add-Finding error receipt.decision "human_decision er ikke GO" }
    if ((Get-PropertyValue $receipt "all_required_observations_passed") -ne $true) { Add-Finding error receipt.observations "Ikke alle observations er pass" }
    foreach ($name in @("credential_data_included", "public_network", "production_activation")) { if ((Get-PropertyValue $receipt $name) -ne $false) { Add-Finding error "receipt.$name" "$name skal være false" } }
    Validate-MainDigest $receipt
    Validate-Fixture (Get-PropertyValue $receipt "fixture")
    Validate-Mutations (Get-PropertyValue $receipt "mutations")
    Validate-Trials (Get-PropertyValue $receipt "trials")
    $pixel = Get-PropertyValue $receipt "pixel"
    $model = [string](Get-PropertyValue $pixel "model")
    if ($model -notmatch '(?i)pixel' -or $model -match '(?i)emulator|qemu|sdk_gphone|generic') { Add-Finding error pixel.model "Fysisk Google Pixel er ikke dokumenteret" }
    if ([string](Get-PropertyValue $pixel "app_package") -ne "dk.ternedal.modelrig") { Add-Finding error pixel.package "Forkert app package" }
    foreach ($name in @("android_release", "sdk", "version_name_line", "version_code_line")) { if ([string]::IsNullOrWhiteSpace([string](Get-PropertyValue $pixel $name))) { Add-Finding error "pixel.$name" "$name mangler" } }
    $cleanup = Get-PropertyValue $receipt "cleanup"
    foreach ($name in @("backend_stopped", "worker_stopped", "firewall_removed", "ports_free", "admin_key_deleted", "passed")) { if ((Get-PropertyValue $cleanup $name) -ne $true) { Add-Finding error "cleanup.$name" "$name skal være true" } }
    if ((Get-PropertyValue $cleanup "unknown_process_preserved") -ne $false) { Add-Finding error cleanup.unknown "unknown_process_preserved skal være false" }
    Validate-Artifacts (Get-PropertyValue $receipt "artifacts")

    $errors = @($Findings | Where-Object { $_.level -eq "error" })
    $warnings = @($Findings | Where-Object { $_.level -eq "warning" })
    $report = [ordered]@{
        schema = "modelrig-agent4/physical-read-audit/v1"
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        verdict = if ($errors.Count -eq 0) { "PASS" } else { "FAIL" }
        expected_sha = $head
        expected_branch = $ExpectedBranch
        frozen_main_anchor = $FrozenMainAnchor
        receipt = [ordered]@{ path = (Resolve-Path $ReceiptPath).Path; size_bytes = (Get-Item $ReceiptPath).Length; sha256 = "sha256:$((Get-FileHash $ReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant())" }
        error_count = $errors.Count
        warning_count = $warnings.Count
        findings = @($Findings)
        credential_data_included = $false
        production_activation = $false
    }
    $report["audit_sha256"] = Get-Sha256ForText (($report | ConvertTo-Json -Depth 20 -Compress))
    $parent = Split-Path -Parent $OutputPath
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    Write-Host "A4-18 RECEIPT AUDIT: $($report.verdict)" -ForegroundColor $(if ($errors.Count -eq 0) { "Green" } else { "Red" })
    Write-Host "Rapport: $OutputPath" -ForegroundColor Cyan
    foreach ($finding in @($Findings | Where-Object { $_.level -ne "info" })) { Write-Host "[$($finding.level.ToUpperInvariant())] $($finding.code): $($finding.message)" }
    if ($errors.Count -ne 0) { exit 2 }
    exit 0
}
catch {
    Write-Error "A4-18 auditoren kunne ikke gennemføre: $($_.Exception.Message)"
    exit 3
}
