# BodyRig private-input parity inventory.
#
# This script never copies licensed/private model bytes. It records hashes and
# counts for the exact assets the installed BodyRig runtime consumes, then can
# compare another rig against that evidence after BodyRig provisioning.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Capture", "Verify")]
    [string]$Action,

    [string]$Manifest = "",
    [string]$OutFile = "",
    [string]$BodyRigRepo = "C:\Rig\src\BodyRig",
    [string]$RecoverySummary = "",
    [string]$SithSetupReport = "",
    [string]$BodyRigPython = "",
    [string]$WslExe = "wsl.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Schema = "bodyrig-private-input-inventory/v1"

function Resolve-ExistingFile {
    param([string]$Path, [string]$Description)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-ExistingDirectory {
    param([string]$Path, [string]$Description)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Description not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Read-JsonFile {
    param([string]$Path, [string]$Description)
    try {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
    } catch {
        throw "$Description is not valid JSON: $($_.Exception.Message)"
    }
}

function Resolve-BodyRigPython {
    if (-not [string]::IsNullOrWhiteSpace($BodyRigPython)) {
        return Resolve-ExistingFile -Path $BodyRigPython -Description "BodyRig Python"
    }

    $repo = Resolve-ExistingDirectory -Path $BodyRigRepo -Description "BodyRig repository"
    $venv = Join-Path $repo ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venv -PathType Leaf) {
        return (Resolve-Path -LiteralPath $venv).Path
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) {
        throw "BodyRig Python was not found. Pass -BodyRigPython or provision the BodyRig .venv first."
    }
    return $python.Source
}

function Resolve-WslExecutable {
    if (Test-Path -LiteralPath $WslExe -PathType Leaf) {
        return (Resolve-Path -LiteralPath $WslExe).Path
    }
    $command = Get-Command $WslExe -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "WSL executable not found: $WslExe"
    }
    return $command.Source
}

function Invoke-BodyRigJson {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $previousPreference = $ErrorActionPreference
    $output = @()
    $exitCode = 1
    try {
        # Windows PowerShell 5.1 can surface native stderr as PowerShell error
        # records. The child process exit code remains the authority.
        $ErrorActionPreference = "Continue"
        $output = @(& $Python @Arguments)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }
    $text = ($output -join "`n").Trim()
    try {
        return ($text | ConvertFrom-Json)
    } catch {
        throw "$Description returned invalid JSON."
    }
}

function Assert-Digest {
    param(
        [object]$Digest,
        [string]$Description,
        [switch]$Tree
    )
    $sha = ([string]$Digest.sha256).Trim().ToLowerInvariant()
    if ($sha -notmatch '^[0-9a-f]{64}$') {
        throw "$Description returned an invalid SHA-256 digest."
    }
    if ([int64]$Digest.byte_count -lt 1) {
        throw "$Description returned an invalid byte count."
    }
    if ($Tree -and [int64]$Digest.file_count -lt 1) {
        throw "$Description returned an invalid file count."
    }
}

function Get-CurrentInventory {
    $localAppData = [string]$env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($localAppData) -and
        ([string]::IsNullOrWhiteSpace($RecoverySummary) -or [string]::IsNullOrWhiteSpace($SithSetupReport))) {
        throw "LOCALAPPDATA is unavailable; pass -RecoverySummary and -SithSetupReport explicitly."
    }

    $recoveryPath = if ([string]::IsNullOrWhiteSpace($RecoverySummary)) {
        Join-Path $localAppData "BodyRig\recovery\bodyrig-recovery-environment.json"
    } else {
        $RecoverySummary
    }
    $sithPath = if ([string]::IsNullOrWhiteSpace($SithSetupReport)) {
        Join-Path $localAppData "BodyRig\sith\setup-report.json"
    } else {
        $SithSetupReport
    }

    $recoveryPath = Resolve-ExistingFile -Path $recoveryPath -Description "BodyRig recovery environment summary"
    $sithPath = Resolve-ExistingFile -Path $sithPath -Description "BodyRig SiTH setup report"
    $recovery = Read-JsonFile -Path $recoveryPath -Description "BodyRig recovery environment summary"
    $sith = Read-JsonFile -Path $sithPath -Description "BodyRig SiTH setup report"

    if ([string]$recovery.format -ne "bodyrig-recovery-environment" -or [int]$recovery.version -ne 1 -or $recovery.smpl_present -ne $true) {
        throw "BodyRig recovery environment summary is not READY."
    }
    if ([string]$sith.format -ne "bodyrig-sith-setup" -or [int]$sith.version -lt 4) {
        throw "BodyRig SiTH setup report does not provide the required v4+ digest contract."
    }

    $smplPath = Resolve-ExistingFile -Path ([string]$recovery.smpl_expected_path) -Description "Installed BodyRig SMPL model"
    $smplFile = Get-Item -LiteralPath $smplPath
    $smplSha = (Get-FileHash -LiteralPath $smplPath -Algorithm SHA256).Hash.ToLowerInvariant()

    $distribution = ([string]$sith.distribution).Trim()
    $sithRepo = ([string]$sith.sith.repository).TrimEnd('/')
    $sithPython = ([string]$sith.sith.python).Trim()
    $diffusionPath = ([string]$sith.diffusion_model.path).Trim()
    if ([string]::IsNullOrWhiteSpace($distribution) -or
        [string]::IsNullOrWhiteSpace($sithRepo) -or -not $sithRepo.StartsWith('/') -or
        [string]::IsNullOrWhiteSpace($sithPython) -or -not $sithPython.StartsWith('/') -or
        [string]::IsNullOrWhiteSpace($diffusionPath) -or -not $diffusionPath.StartsWith('/')) {
        throw "BodyRig SiTH setup report contains invalid WSL runtime paths."
    }

    $python = Resolve-BodyRigPython
    $wsl = Resolve-WslExecutable
    $smplxPath = "$sithRepo/data/body_models/smplx"
    $smplx = Invoke-BodyRigJson -Python $python -Description "Installed SMPL-X runtime tree digest" -Arguments @(
        "-m", "bodyrig.wsl_tree_digest",
        "--distribution", $distribution,
        "--python", $sithPython,
        "--path", $smplxPath,
        "--wsl-exe", $wsl
    )
    Assert-Digest -Digest $smplx -Description "Installed SMPL-X runtime tree digest" -Tree

    $diffusion = Invoke-BodyRigJson -Python $python -Description "Installed SiTH diffusion model digest" -Arguments @(
        "-m", "bodyrig.sith_model",
        "--distribution", $distribution,
        "--python", $sithPython,
        "--model-path", $diffusionPath,
        "--wsl-exe", $wsl
    )
    Assert-Digest -Digest $diffusion -Description "Installed SiTH diffusion model digest" -Tree

    $reportedDiffusionSha = ([string]$sith.diffusion_model.sha256).Trim().ToLowerInvariant()
    if ($reportedDiffusionSha -notmatch '^[0-9a-f]{64}$' -or $reportedDiffusionSha -ne ([string]$diffusion.sha256).ToLowerInvariant()) {
        throw "Live SiTH diffusion model digest no longer matches the validated BodyRig setup report. Re-run BodyRig setup before capturing migration evidence."
    }

    $bodyRigRevision = ""
    try {
        $repo = Resolve-ExistingDirectory -Path $BodyRigRepo -Description "BodyRig repository"
        $bodyRigRevision = (& git -C $repo rev-parse HEAD 2>$null | Select-Object -First 1).Trim()
        if ($LASTEXITCODE -ne 0) { $bodyRigRevision = "" }
    } catch {
        $bodyRigRevision = ""
    }

    return [ordered]@{
        schema = $Schema
        captured_utc = [DateTime]::UtcNow.ToString("o")
        computer = $env:COMPUTERNAME
        bodyrig_revision = $bodyRigRevision
        evidence = [ordered]@{
            recovery_summary = $recoveryPath
            sith_setup_report = $sithPath
            distribution = $distribution
        }
        assets = [ordered]@{
            smpl = [ordered]@{
                runtime_path = $smplPath
                sha256 = $smplSha
                byte_count = [int64]$smplFile.Length
            }
            smplx = [ordered]@{
                runtime_path = $smplxPath
                sha256 = ([string]$smplx.sha256).ToLowerInvariant()
                file_count = [int64]$smplx.file_count
                byte_count = [int64]$smplx.byte_count
            }
            diffusion_model = [ordered]@{
                runtime_path = $diffusionPath
                sha256 = ([string]$diffusion.sha256).ToLowerInvariant()
                file_count = [int64]$diffusion.file_count
                byte_count = [int64]$diffusion.byte_count
            }
        }
        payload_bytes_included = $false
        note = "Evidence only. Licensed/private BodyRig model bytes are not included."
    }
}

function Assert-AssetParity {
    param([object]$Expected, [object]$Actual, [string]$Name, [switch]$Tree)

    $fields = @("sha256", "byte_count")
    if ($Tree) { $fields += "file_count" }
    foreach ($field in $fields) {
        $want = [string]$Expected.$field
        $got = [string]$Actual.$field
        if ($want -ne $got) {
            throw "BodyRig private input mismatch for $Name.$field (expected $want, got $got)."
        }
    }
}

if ($Action -eq "Capture") {
    $inventory = Get-CurrentInventory
    if ([string]::IsNullOrWhiteSpace($OutFile)) {
        $base = Join-Path $env:USERPROFILE "RigMigration"
        New-Item -ItemType Directory -Path $base -Force | Out-Null
        $OutFile = Join-Path $base ("bodyrig-private-inputs-{0}.json" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
    }
    $parent = Split-Path -Parent ([IO.Path]::GetFullPath($OutFile))
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $target = [IO.Path]::GetFullPath($OutFile)
    $temp = "$target.tmp-$([Guid]::NewGuid().ToString('N'))"
    $json = $inventory | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($temp, $json + "`n", [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $target -Force
    Write-Host "BODYRIG PRIVATE INPUT INVENTORY CAPTURED: $target" -ForegroundColor Green
    Write-Host "No licensed/private model bytes were copied." -ForegroundColor Yellow
    exit 0
}

$manifestPath = Resolve-ExistingFile -Path $Manifest -Description "BodyRig private input inventory"
$expected = Read-JsonFile -Path $manifestPath -Description "BodyRig private input inventory"
if ([string]$expected.schema -ne $Schema) {
    throw "Unsupported BodyRig private input inventory schema: $($expected.schema)"
}
if ($expected.payload_bytes_included -ne $false) {
    throw "BodyRig inventory claims payload bytes are included; refusing an unexpected manifest contract."
}

$actual = Get-CurrentInventory
Assert-AssetParity -Expected $expected.assets.smpl -Actual $actual.assets.smpl -Name "SMPL"
Assert-AssetParity -Expected $expected.assets.smplx -Actual $actual.assets.smplx -Name "SMPL-X" -Tree
Assert-AssetParity -Expected $expected.assets.diffusion_model -Actual $actual.assets.diffusion_model -Name "SiTH diffusion model" -Tree

Write-Host "BODYRIG PRIVATE INPUT PARITY VERIFIED" -ForegroundColor Green
Write-Host "SMPL, installed SMPL-X runtime tree, and SiTH diffusion model match the source evidence byte-for-byte." -ForegroundColor Green
exit 0
