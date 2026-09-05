# Complete old-rig -> new-rig migration orchestrator.
#
# This script deliberately composes the repository-owned ModelRig and VoiceRig
# migration operators. It does not duplicate either archive format or weaken
# their fail-closed service boundaries.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Export", "Import", "Verify")]
    [string]$Action,

    [string]$InstallRoot = "C:\Rig",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$ModelRigRuntimeRoot = "",
    [string]$VoiceRigRepo = "",
    [string]$OutDir = (Join-Path $env:USERPROFILE "RigMigration"),
    [string]$Bundle = "",
    [int]$MinimumGpuCount = 1,

    [switch]$ForceRestore,
    [switch]$SkipFinalValidation,

    # Dependency-injection hooks are useful for CI/operator testing. Normal rig
    # use should leave these empty so repository-owned paths are selected.
    [string]$ModelRigOperator = "",
    [string]$VoiceRigOperator = "",
    [string]$BootstrapScript = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$BundleSchema = "complete-rig-migration/v1"
$BundleManifestName = "rig-migration.json"

function Write-Step {
    param([string]$Text)
    Write-Host ("== {0} ==" -f $Text) -ForegroundColor Cyan
}

function Resolve-ExistingFile {
    param([string]$Path, [string]$Description)
    if ([string]::IsNullOrWhiteSpace($Path) -or
        -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Resolve-ExistingDirectory {
    param([string]$Path, [string]$Description)
    if ([string]::IsNullOrWhiteSpace($Path) -or
        -not (Test-Path -LiteralPath $Path -PathType Container)) {
        throw "$Description not found: $Path"
    }
    return (Resolve-Path -LiteralPath $Path).Path
}

function Assert-CanonicalModelRigRuntime {
    param([string]$Runtime, [string]$Root)

    $expected = [IO.Path]::GetFullPath((Join-Path $Root "ModelRig")).TrimEnd('\')
    $actual = [IO.Path]::GetFullPath($Runtime).TrimEnd('\')
    if (-not [string]::Equals($actual, $expected, [StringComparison]::OrdinalIgnoreCase)) {
        throw ("Complete rig migration requires ModelRigRuntimeRoot to equal InstallRoot\\ModelRig so the final bootstrap validation cannot inspect a different appliance. " +
            "Expected '{0}', got '{1}'. Use the standalone ModelRig migration operator for non-canonical layouts.") -f $expected, $actual
    }
    return $expected
}

function Resolve-VoiceRigRepository {
    if (-not [string]::IsNullOrWhiteSpace($VoiceRigRepo)) {
        $resolved = Resolve-ExistingDirectory -Path $VoiceRigRepo -Description "VoiceRig repository"
        $operator = Join-Path $resolved "migrate-state-windows.ps1"
        if (-not (Test-Path -LiteralPath $operator -PathType Leaf)) {
            throw "VoiceRig checkout at '$resolved' does not contain migrate-state-windows.ps1. Update VoiceRig to a revision with rig migration support."
        }
        return $resolved
    }

    $candidates = New-Object System.Collections.Generic.List[string]
    $candidates.Add((Join-Path $InstallRoot "src\VoiceRig"))
    $repoParent = Split-Path -Parent $RepoRoot
    if (-not [string]::IsNullOrWhiteSpace($repoParent)) {
        $candidates.Add((Join-Path $repoParent "VoiceRig"))
    }

    foreach ($candidate in @($candidates | Select-Object -Unique)) {
        if (Test-Path -LiteralPath (Join-Path $candidate "migrate-state-windows.ps1") -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw ("VoiceRig migration checkout was not found. Expected '{0}' or a sibling VoiceRig checkout. " +
        "Pass -VoiceRigRepo explicitly if the old rig uses another location.") -f (Join-Path $InstallRoot "src\VoiceRig")
}

function Resolve-OperatorPaths {
    $resolvedRepo = Resolve-ExistingDirectory -Path $RepoRoot -Description "ModelRig repository"
    $resolvedVoiceRepo = Resolve-VoiceRigRepository

    $modelOperator = if ([string]::IsNullOrWhiteSpace($ModelRigOperator)) {
        Join-Path $resolvedRepo "scripts\migrate-new-rig-state.ps1"
    } else {
        $ModelRigOperator
    }
    $voiceOperator = if ([string]::IsNullOrWhiteSpace($VoiceRigOperator)) {
        Join-Path $resolvedVoiceRepo "migrate-state-windows.ps1"
    } else {
        $VoiceRigOperator
    }
    $bootstrap = if ([string]::IsNullOrWhiteSpace($BootstrapScript)) {
        Join-Path $resolvedRepo "scripts\bootstrap-new-rig.ps1"
    } else {
        $BootstrapScript
    }

    return [pscustomobject]@{
        RepoRoot = $resolvedRepo
        VoiceRigRepo = $resolvedVoiceRepo
        ModelRigOperator = Resolve-ExistingFile -Path $modelOperator -Description "ModelRig migration operator"
        VoiceRigOperator = Resolve-ExistingFile -Path $voiceOperator -Description "VoiceRig migration operator"
        BootstrapScript = Resolve-ExistingFile -Path $bootstrap -Description "New-rig bootstrap"
    }
}

function Invoke-PowerShellOperator {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Get-Command powershell.exe -ErrorAction SilentlyContinue)) {
        throw "powershell.exe was not found; the complete migration operator requires Windows PowerShell."
    }

    Write-Host "Running $Label..."
    $previousPreference = $ErrorActionPreference
    $exitCode = 1
    try {
        # Windows PowerShell 5.1 can surface native stderr as PowerShell error
        # records. Let the child process' exit code remain the authority.
        $ErrorActionPreference = "Continue"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Path @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode."
    }
}

function Get-ModelRigProcesses {
    return @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -like "modelrig-*"
    })
}

function Assert-ModelRigStopped {
    $processes = @(Get-ModelRigProcesses)
    if ($processes.Count -gt 0) {
        $names = @($processes | ForEach-Object { $_.ProcessName + "(" + $_.Id + ")" }) -join ", "
        throw "ModelRig must remain stopped across the complete migration boundary, but these processes are live: $names"
    }
}

function Test-ModelRigWasRunning {
    $processes = @(Get-ModelRigProcesses)
    if ($processes.Count -gt 0) { return $true }

    foreach ($taskName in @("KalivBootstrap", "KalivSupervisor")) {
        try {
            $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
            if ([string]$task.State -eq "Running") { return $true }
        } catch {}
    }
    return $false
}

function Resume-HeldModelRig {
    $processes = @(Get-ModelRigProcesses)
    if ($processes.Count -gt 0) {
        Write-Host "ModelRig is already running; no recovery-first restart is needed."
        return
    }

    try {
        Get-ScheduledTask -TaskName "KalivBootstrap" -ErrorAction Stop | Out-Null
        Start-ScheduledTask -TaskName "KalivBootstrap"
        Write-Host "Started 'KalivBootstrap' (recovery-first startup)."
    } catch {
        throw "ModelRig was held down for complete migration, but KalivBootstrap could not be started: $($_.Exception.Message)"
    }
}

function New-UniqueBundleDirectory {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    $resolvedParent = (Resolve-Path -LiteralPath $OutDir).Path
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $suffix = [Guid]::NewGuid().ToString("N").Substring(0, 8)
        $candidate = Join-Path $resolvedParent ("rig-migration-{0}-{1}" -f $stamp, $suffix)
        if (-not (Test-Path -LiteralPath $candidate)) {
            New-Item -ItemType Directory -Path $candidate | Out-Null
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    throw "Could not allocate a unique rig migration bundle directory."
}

function Get-SingleArtifact {
    param(
        [string]$Directory,
        [string]$Filter,
        [string]$Description
    )
    $matches = @(Get-ChildItem -LiteralPath $Directory -Filter $Filter -File -ErrorAction Stop)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one $Description matching '$Filter' in '$Directory'; found $($matches.Count)."
    }
    return $matches[0].FullName
}

function Get-ArtifactHash {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-JsonFile {
    param([string]$Path, [string]$Description)
    try {
        return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json)
    } catch {
        throw "$Description is not valid JSON: $($_.Exception.Message)"
    }
}

function Get-SafeLeafName {
    param([object]$Value, [string]$Description)
    $name = [string]$Value
    if ([string]::IsNullOrWhiteSpace($name) -or
        [IO.Path]::IsPathRooted($name) -or
        [IO.Path]::GetFileName($name) -ne $name -or
        $name.IndexOf('/') -ge 0 -or $name.IndexOf('\') -ge 0) {
        throw "$Description must be a relative leaf filename, got '$name'."
    }
    return $name
}

function Resolve-BundleManifest {
    if ([string]::IsNullOrWhiteSpace($Bundle)) {
        throw "-Bundle is required for $Action. Pass the bundle directory or its $BundleManifestName file."
    }
    if (Test-Path -LiteralPath $Bundle -PathType Container) {
        $candidate = Join-Path $Bundle $BundleManifestName
        return Resolve-ExistingFile -Path $candidate -Description "Complete rig migration manifest"
    }
    return Resolve-ExistingFile -Path $Bundle -Description "Complete rig migration manifest"
}

function Resolve-BundleEntry {
    param(
        [string]$BundleDirectory,
        [object]$Entry,
        [string]$Kind
    )

    if ($null -eq $Entry) {
        throw "Complete rig migration manifest is missing '$Kind'."
    }
    $archiveName = Get-SafeLeafName -Value $Entry.archive -Description "$Kind archive"
    $sidecarName = Get-SafeLeafName -Value $Entry.sidecar -Description "$Kind sidecar"
    $archivePath = Resolve-ExistingFile -Path (Join-Path $BundleDirectory $archiveName) -Description "$Kind archive"
    $sidecarPath = Resolve-ExistingFile -Path (Join-Path $BundleDirectory $sidecarName) -Description "$Kind sidecar"

    $wantArchiveHash = ([string]$Entry.archive_sha256).Trim().ToLowerInvariant()
    $wantSidecarHash = ([string]$Entry.sidecar_sha256).Trim().ToLowerInvariant()
    if ($wantArchiveHash -notmatch '^[0-9a-f]{64}$' -or
        $wantSidecarHash -notmatch '^[0-9a-f]{64}$') {
        throw "$Kind manifest hashes are missing or malformed."
    }
    $gotArchiveHash = Get-ArtifactHash -Path $archivePath
    $gotSidecarHash = Get-ArtifactHash -Path $sidecarPath
    if ($gotArchiveHash -ne $wantArchiveHash) {
        throw "$Kind archive SHA-256 does not match the complete bundle manifest."
    }
    if ($gotSidecarHash -ne $wantSidecarHash) {
        throw "$Kind sidecar SHA-256 does not match the complete bundle manifest."
    }

    return [pscustomobject]@{
        Archive = $archivePath
        Sidecar = $sidecarPath
    }
}

function Get-VerifiedBundle {
    param([object]$Paths)

    $manifestPath = Resolve-BundleManifest
    $bundleDirectory = Split-Path -Parent $manifestPath
    $manifest = Read-JsonFile -Path $manifestPath -Description "Complete rig migration manifest"
    if ([string]$manifest.schema -ne $BundleSchema) {
        throw "Unsupported complete rig migration schema: $($manifest.schema)"
    }

    $model = Resolve-BundleEntry -BundleDirectory $bundleDirectory -Entry $manifest.modelrig -Kind "ModelRig"
    $voice = Resolve-BundleEntry -BundleDirectory $bundleDirectory -Entry $manifest.voicerig -Kind "VoiceRig"

    Write-Step "Verifying ModelRig migration archive"
    Invoke-PowerShellOperator -Path $Paths.ModelRigOperator -Label "ModelRig archive verification" -Arguments @(
        "-Action", "Verify",
        "-RepoRoot", $Paths.RepoRoot,
        "-Archive", $model.Archive
    )

    Write-Step "Verifying VoiceRig migration archive"
    Invoke-PowerShellOperator -Path $Paths.VoiceRigOperator -Label "VoiceRig archive verification" -Arguments @(
        "-Action", "Verify",
        "-Archive", $voice.Archive
    )

    return [pscustomobject]@{
        ManifestPath = $manifestPath
        BundleDirectory = $bundleDirectory
        Manifest = $manifest
        ModelRigArchive = $model.Archive
        VoiceRigArchive = $voice.Archive
    }
}

function Write-BundleManifest {
    param(
        [string]$Directory,
        [string]$ModelArchive,
        [string]$VoiceArchive
    )

    $modelSidecar = $ModelArchive + ".migration.json"
    $voiceSidecar = $VoiceArchive + ".migration.json"
    Resolve-ExistingFile -Path $modelSidecar -Description "ModelRig migration sidecar" | Out-Null
    Resolve-ExistingFile -Path $voiceSidecar -Description "VoiceRig migration sidecar" | Out-Null

    $modelMeta = Read-JsonFile -Path $modelSidecar -Description "ModelRig migration sidecar"
    $voiceMeta = Read-JsonFile -Path $voiceSidecar -Description "VoiceRig migration sidecar"

    $manifest = [ordered]@{
        schema = $BundleSchema
        created_utc = [DateTime]::UtcNow.ToString("o")
        source_computer = $env:COMPUTERNAME
        modelrig = [ordered]@{
            archive = Split-Path -Leaf $ModelArchive
            sidecar = Split-Path -Leaf $modelSidecar
            archive_sha256 = Get-ArtifactHash -Path $ModelArchive
            sidecar_sha256 = Get-ArtifactHash -Path $modelSidecar
            source_revision = $modelMeta.repo_head
        }
        voicerig = [ordered]@{
            archive = Split-Path -Leaf $VoiceArchive
            sidecar = Split-Path -Leaf $voiceSidecar
            archive_sha256 = Get-ArtifactHash -Path $VoiceArchive
            sidecar_sha256 = Get-ArtifactHash -Path $voiceSidecar
            source_revision = $voiceMeta.source_revision
            contains_private_job_inputs = [bool]$voiceMeta.contains_private_job_inputs
        }
        manual_inputs_not_bundled = @(
            "ModelRig/VoiceRig secret values and credentials",
            "BodyRig licensed SMPL/SMPL-X assets",
            "BodyRig private/local SiTH diffusion model"
        )
    }

    $manifestPath = Join-Path $Directory $BundleManifestName
    $temporary = "$manifestPath.tmp"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $manifestPath -Force
    return $manifestPath
}

$paths = Resolve-OperatorPaths
$runtimeRoot = if ([string]::IsNullOrWhiteSpace($ModelRigRuntimeRoot)) {
    Join-Path $InstallRoot "ModelRig"
} else {
    $ModelRigRuntimeRoot
}
if ($Action -ne "Verify") {
    $runtimeRoot = Assert-CanonicalModelRigRuntime -Runtime $runtimeRoot -Root $InstallRoot
}

if ($Action -eq "Export") {
    Write-Step "Creating complete migration bundle"
    $bundleDirectory = New-UniqueBundleDirectory
    $completed = $false
    $exportFailure = $null
    $modelRigWasRunning = Test-ModelRigWasRunning

    try {
        # Hold ModelRig down after its own consistent DB snapshot. VoiceRig then
        # snapshots the shared ModelRig voice directory while ModelRig cannot
        # change its default/package files. VoiceRig's own operator still owns
        # its stop/restart boundary. This gives the complete bundle one coherent
        # cross-system voice/default boundary without reimplementing either
        # archive format.
        Write-Step "Exporting ModelRig/Kaliv state and holding ModelRig stopped"
        Invoke-PowerShellOperator -Path $paths.ModelRigOperator -Label "ModelRig state export" -Arguments @(
            "-Action", "Export",
            "-RuntimeRoot", $runtimeRoot,
            "-RepoRoot", $paths.RepoRoot,
            "-OutDir", $bundleDirectory,
            "-MinimumGpuCount", ([string]$MinimumGpuCount),
            "-SkipRestart"
        )
        $modelArchive = Get-SingleArtifact -Directory $bundleDirectory -Filter "kaliv-backup-*.tar.gz" -Description "ModelRig archive"
        Resolve-ExistingFile -Path ($modelArchive + ".migration.json") -Description "ModelRig migration sidecar" | Out-Null

        Write-Step "Exporting VoiceRig state while ModelRig remains stopped"
        Assert-ModelRigStopped
        Invoke-PowerShellOperator -Path $paths.VoiceRigOperator -Label "VoiceRig state export" -Arguments @(
            "-Action", "Export",
            "-OutDir", $bundleDirectory
        )
        Assert-ModelRigStopped
        $voiceArchive = Get-SingleArtifact -Directory $bundleDirectory -Filter "voicerig-migration-*.tar.gz" -Description "VoiceRig archive"
        Resolve-ExistingFile -Path ($voiceArchive + ".migration.json") -Description "VoiceRig migration sidecar" | Out-Null

        $manifestPath = Write-BundleManifest -Directory $bundleDirectory -ModelArchive $modelArchive -VoiceArchive $voiceArchive
        $script:Bundle = $manifestPath
        [void](Get-VerifiedBundle -Paths $paths)
        $completed = $true
    } catch {
        $exportFailure = $_
    } finally {
        if ($modelRigWasRunning) {
            try {
                Resume-HeldModelRig
            } catch {
                if ($exportFailure) {
                    Write-Warning "Complete export also failed to restore the old ModelRig runtime: $($_.Exception.Message)"
                } else {
                    $exportFailure = $_
                }
            }
        }
        if (-not $completed) {
            Write-Warning "Complete export did not finish. '$bundleDirectory' is an incomplete evidence directory and must not be used for cutover."
        }
    }

    if ($exportFailure) { throw $exportFailure }
    Write-Host "COMPLETE RIG EXPORT READY: $bundleDirectory" -ForegroundColor Green
    Write-Host "Copy the entire directory to the new rig; do not separate its manifest, archives or sidecars."
    return
}

$verified = Get-VerifiedBundle -Paths $paths
if ($Action -eq "Verify") {
    Write-Host "COMPLETE RIG BUNDLE VERIFIED: $($verified.BundleDirectory)" -ForegroundColor Green
    if ($verified.Manifest.voicerig.contains_private_job_inputs -eq $true) {
        Write-Warning "The bundle contains private VoiceRig source audio/video for resumable jobs. Treat the whole bundle as sensitive."
    }
    return
}

$modelImported = $false
$voiceImported = $false
try {
    Write-Step "Importing ModelRig/Kaliv state and holding ModelRig stopped"
    $modelArgs = @(
        "-Action", "Import",
        "-RuntimeRoot", $runtimeRoot,
        "-RepoRoot", $paths.RepoRoot,
        "-Archive", $verified.ModelRigArchive,
        "-MinimumGpuCount", ([string]$MinimumGpuCount),
        "-SkipValidation",
        "-SkipRestart"
    )
    if ($ForceRestore) { $modelArgs += "-ForceRestore" }
    Invoke-PowerShellOperator -Path $paths.ModelRigOperator -Label "ModelRig state import" -Arguments $modelArgs
    $modelImported = $true
    Assert-ModelRigStopped

    Write-Step "Importing VoiceRig state while ModelRig remains stopped"
    $voiceArgs = @(
        "-Action", "Import",
        "-Archive", $verified.VoiceRigArchive
    )
    if ($ForceRestore) { $voiceArgs += "-ForceRestore" }
    Invoke-PowerShellOperator -Path $paths.VoiceRigOperator -Label "VoiceRig state import" -Arguments $voiceArgs
    $voiceImported = $true
    Assert-ModelRigStopped

    Write-Step "Starting restored ModelRig through recovery-first bootstrap"
    Resume-HeldModelRig

    if (-not $SkipFinalValidation) {
        Write-Step "Running one final new-rig validation"
        Invoke-PowerShellOperator -Path $paths.BootstrapScript -Label "Final new-rig validation" -Arguments @(
            "-Phase", "Validate",
            "-InstallRoot", $InstallRoot,
            "-MinimumGpuCount", ([string]$MinimumGpuCount),
            "-SkipBodyRig"
        )
    }

    Write-Host "COMPLETE RIG IMPORT FINISHED: ModelRig + VoiceRig state restored." -ForegroundColor Green
    Write-Host "Keep the old rig intact until a real Kaliv client connection and an audible VoiceRig TTS request have also passed." -ForegroundColor Yellow
} catch {
    if ($modelImported -or $voiceImported) {
        Write-Warning ("Complete import is PARTIAL (ModelRig={0}, VoiceRig={1}). Do not cut over and do not decommission the old rig." -f $modelImported, $voiceImported)
    } else {
        Write-Warning "Complete import failed before either state import completed. Do not cut over."
    }
    throw
}