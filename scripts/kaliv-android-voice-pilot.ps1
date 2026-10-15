# Isolated Android voice pilot. Does not touch 8080/8099, scheduled tasks,
# installed app, protected main, or the production device-token store.
[CmdletBinding()]
param(
    [string]$WorkerExe = "C:\Rig\test\kaliv-voice-e01b2d1c\modelrig-worker-windows-x64.exe",
    [string]$BackendExe,
    [string]$LanIp,
    [ValidateRange(1024,65535)][int]$WorkerPort = 18121,
    [ValidateRange(1024,65535)][int]$BackendPort = 18180,
    [string]$AudioPath,
    [switch]$SkipProxyVoiceProbe
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$expectedCommit = "e01b2d1c989f4da1d454e004f074870741f409df"
$testRoot = "C:\Rig\test\kaliv-android-voice-pilot"
$workerProcess = $null
$backendProcess = $null
$dataPath = $null
$originalEnv = @{}
$environmentTouched = $false

function Test-PrivateIPv4([string]$Address) {
    $ip = $null
    if (-not [Net.IPAddress]::TryParse($Address, [ref]$ip)) { return $false }
    if ($ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { return $false }
    $b = $ip.GetAddressBytes()
    return ($b[0] -eq 10) -or ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31) -or ($b[0] -eq 192 -and $b[1] -eq 168)
}
function Find-LanIp {
    $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object {
        (Test-PrivateIPv4 $_.IPAddress) -and $_.AddressState -eq "Preferred" -and
        $_.InterfaceAlias -notmatch "vEthernet|WSL|Docker|Hyper-V|VMware|VirtualBox|Loopback"
    })
    if ($addresses.Count -ne 1) {
        $choices = ($addresses | ForEach-Object { "$($_.IPAddress) ($($_.InterfaceAlias))" }) -join ", "
        throw "Flere eller ingen mulige LAN-adresser ($choices). Angiv -LanIp med riggens Wi-Fi/Ethernet IPv4."
    }
    return [string]$addresses[0].IPAddress
}
function Wait-Ready([string]$Url, [System.Diagnostics.Process]$Process) {
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) { throw "Testprocessen afsluttede foer $Url blev klar (exit $($Process.ExitCode))." }
        try { return Invoke-RestMethod -Uri $Url -TimeoutSec 3 -ErrorAction Stop }
        catch { Start-Sleep -Seconds 2 }
    }
    throw "Ingen svar fra $Url efter 90 sekunder."
}
function Stop-OwnedProcess([System.Diagnostics.Process]$Process) {
    if ($null -eq $Process) { return }
    try {
        $Process.Refresh()
        if (-not $Process.HasExited) { & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null }
    } catch { Write-Warning "Kunne ikke stoppe testproces $($Process.Id): $_" }
}
function Resolve-Backend([string]$Explicit) {
    if ($Explicit) {
        if (-not (Test-Path -LiteralPath $Explicit -PathType Leaf)) { throw "Backend findes ikke: $Explicit" }
        return (Resolve-Path -LiteralPath $Explicit).Path
    }
    $paths = New-Object System.Collections.Generic.List[string]
    try {
        Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object { $_.Name -match '^modelrig-server.*\.exe$' -and $_.ExecutablePath } |
            ForEach-Object { $paths.Add([string]$_.ExecutablePath) }
    } catch { }
    foreach ($path in @(
        "C:\Rig\test\kaliv-android-voice-pilot\modelrig-server-pilot.exe",
        "C:\Rig\src\ModelRig\modelrig-server-windows-x64.exe",
        "C:\Rig\src\ModelRig\backend\modelrig-server.exe",
        "C:\Rig\src\ModelRig\backend\modelrig-server-windows-x64.exe",
        "C:\Rig\modelrig-server-windows-x64.exe"
    )) { $paths.Add($path) }
    foreach ($path in $paths) {
        if (Test-Path -LiteralPath $path -PathType Leaf) { return (Resolve-Path -LiteralPath $path).Path }
    }
    throw "Ingen ModelRig backend-EXE fundet. Angiv -BackendExe med stien til modelrig-server*.exe."
}
function New-AdminKey {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}
function Get-PairCode([string]$Base, [string]$AdminKey) {
    return Invoke-RestMethod -Method Post -Uri "$Base/api/v1/pair/start" -Headers @{ "X-Admin-Key" = $AdminKey } -TimeoutSec 10
}

try {
    if ($env:OS -ne "Windows_NT") { throw "Pilot-scriptet kraever Windows." }
    if ($WorkerPort -eq $BackendPort -or @(8080,8099) -contains $WorkerPort -or @(8080,8099) -contains $BackendPort) {
        throw "Pilot-porte maa ikke overlappe hinanden eller produktionsportene 8080/8099."
    }
    if (-not (Test-Path -LiteralPath $WorkerExe -PathType Leaf)) { throw "Worker findes ikke: $WorkerExe" }
    $workerExePath = (Resolve-Path -LiteralPath $WorkerExe).Path
    $workerDir = Split-Path -Parent $workerExePath
    $shaFile = Join-Path $workerDir "WORKER_SHA256.txt"
    $commitFile = Join-Path $workerDir "CANDIDATE_COMMIT.txt"
    if (-not (Test-Path $shaFile) -or -not (Test-Path $commitFile)) {
        throw "Workerens checksum/commit-kvittering mangler."
    }
    $expectedHash = ((Get-Content $shaFile -Raw).Trim() -split '\s+')[0]
    $actualHash = (Get-FileHash -LiteralPath $workerExePath -Algorithm SHA256).Hash
    if ($expectedHash -notmatch '^[0-9a-fA-F]{64}$' -or $actualHash -ne $expectedHash) {
        throw "Worker SHA-256 matcher ikke artifact-kvitteringen."
    }
    if ((Get-Content $commitFile -Raw).Trim() -ne $expectedCommit) {
        throw "Worker er ikke den fysisk kvalificerede kandidat $expectedCommit."
    }
    $backendExePath = Resolve-Backend -Explicit $BackendExe
    # A downloaded CI-built pilot backend is checksum-verified before execution.
    if ((Split-Path -Leaf $backendExePath) -eq "modelrig-server-pilot.exe") {
        $backendShaFile = Join-Path (Split-Path -Parent $backendExePath) "SHA256SUMS.txt"
        if (-not (Test-Path -LiteralPath $backendShaFile -PathType Leaf)) {
            throw "Pilot-backendens SHA256SUMS.txt mangler."
        }
        $backendExpected = ((Get-Content $backendShaFile -Raw).Trim() -split '\s+')[0]
        $backendActual = (Get-FileHash -LiteralPath $backendExePath -Algorithm SHA256).Hash
        if ($backendExpected -notmatch '^[0-9a-fA-F]{64}
    if (-not $LanIp) { $LanIp = Find-LanIp }
    if (-not (Test-PrivateIPv4 $LanIp)) { throw "-LanIp skal vaere en privat IPv4-adresse." }
    if (-not (Get-NetIPAddress -AddressFamily IPv4 -IPAddress $LanIp -ErrorAction SilentlyContinue)) {
        throw "$LanIp findes ikke paa riggens netkort."
    }
    foreach ($port in @($WorkerPort, $BackendPort)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "Port $port er optaget. Eksisterende processer maa ikke stoppes."
        }
    }

    $ollamaUrl = $null
    $model = $null
    foreach ($url in @("http://127.0.0.1:11434", "http://127.0.0.1:11435")) {
        try {
            $tags = Invoke-RestMethod "$url/api/tags" -TimeoutSec 5
            $available = @($tags.models | ForEach-Object { $_.name })
            $choice = @("qwen2.5-coder:7b", "gemma3:12b", "gemma4:26b") | Where-Object { $available -contains $_ } | Select-Object -First 1
            if ($choice) { $ollamaUrl = $url; $model = $choice; break }
        } catch { }
    }
    if (-not $ollamaUrl) { throw "Ingen kendt lokal Ollama-model paa 11434/11435." }

    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $runId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") + "-" + [guid]::NewGuid().ToString("N").Substring(0,6)
    $dataPath = Join-Path $testRoot "pairing-$runId.json"
    $adminKey = New-AdminKey
    $base = "http://{0}:{1}" -f $LanIp, $BackendPort
    $workerBase = "http://127.0.0.1:{0}" -f $WorkerPort

    # Do not inherit experimental activation flags into a test worker/backend.
    Get-ChildItem Env: | Where-Object { $_.Name -match '^(MODELRIG_|KALIV_|ALVA_)' } |
        ForEach-Object { $originalEnv[$_.Name] = $_.Value }
    $environmentTouched = $true
    foreach ($name in @($originalEnv.Keys)) {
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    foreach ($name in @("KALIV_TTS_VOICE", "KALIV_TTS_VOICES_DIR", "KALIV_ASR_MODEL",
                        "KALIV_ASR_COMPUTE", "KALIV_CUDA_DLL_DIRS", "MODELRIG_VENVS_DIR")) {
        if ($originalEnv.ContainsKey($name)) {
            [Environment]::SetEnvironmentVariable($name, $originalEnv[$name], "Process")
        }
    }
    if (-not $env:MODELRIG_VENVS_DIR -and (Test-Path "C:\Rig\venvs" -PathType Container)) {
        $env:MODELRIG_VENVS_DIR = "C:\Rig\venvs"
    }
    $env:MODELRIG_WORKER_HOST = "127.0.0.1"
    $env:MODELRIG_WORKER_PORT = "$WorkerPort"
    $env:MODELRIG_HOST = $LanIp
    $env:MODELRIG_PORT = "$BackendPort"
    $env:MODELRIG_WORKER_URL = $workerBase
    $env:MODELRIG_OLLAMA_URL = $ollamaUrl
    $env:MODELRIG_GEN_MODEL = $model
    $env:MODELRIG_DATA = $dataPath
    $env:MODELRIG_ADMIN_KEY = $adminKey
    $env:KALIV_TTS_PROVIDER = "piper"
    $env:KALIV_ASR_DEVICE = "cuda"

    Write-Host ""
    Write-Host "Starter isoleret worker $workerBase og backend $base" -ForegroundColor Cyan
    Write-Host "Backend EXE: $backendExePath"
    $workerProcess = Start-Process -FilePath $workerExePath -WorkingDirectory $workerDir -PassThru -RedirectStandardOutput (Join-Path $testRoot "worker-$runId.log") -RedirectStandardError (Join-Path $testRoot "worker-$runId.err")
    $null = Wait-Ready "$workerBase/healthz" $workerProcess
    $identity = Invoke-RestMethod "$workerBase/health/full" -TimeoutSec 5
    if ($identity.build.commit_sha -ne $expectedCommit -or
        $identity.build.artifact_sha256 -ne $actualHash.ToLowerInvariant()) {
        throw "Den startede worker har forkert build-identitet."
    }

    $backendProcess = Start-Process -FilePath $backendExePath -WorkingDirectory $testRoot -PassThru -RedirectStandardOutput (Join-Path $testRoot "backend-$runId.log") -RedirectStandardError (Join-Path $testRoot "backend-$runId.err")
    $health = Wait-Ready "$base/healthz" $backendProcess
    if ($health.service -ne "modelrig-server" -or $health.version -ne "2.0.15") {
        throw "Forkert backend: service=$($health.service), version=$($health.version). Kraever 2.0.15."
    }

    $pair = Get-PairCode -Base $base -AdminKey $adminKey
    $claim = Invoke-RestMethod -Method Post -Uri "$base/api/v1/pair/claim" -ContentType "application/json" -Body (@{ code = $pair.code; device_name = "kaliv-voice-pilot-probe" } | ConvertTo-Json) -TimeoutSec 10
    if (-not $claim.token) { throw "Isoleret probe-parring gav intet token." }
    $auth = @{ Authorization = "Bearer $($claim.token)" }
    $status = Invoke-RestMethod -Uri "$base/api/v1/voice/status" -Headers $auth -TimeoutSec 10
    $tts = Invoke-RestMethod -Uri "$workerBase/voice/tts/status" -TimeoutSec 10
    if ($status.available -ne $true -or $tts.available -ne $true) {
        throw "Backendens voice/status eller workerens tts/status rapporterer utilgaengelig stemme."
    }
    Write-Host "PASS: Android-backendens Bearer-auth og voice/status -> worker." -ForegroundColor Green

    if (-not $SkipProxyVoiceProbe) {
        if (-not $AudioPath) {
            foreach ($candidate in @(
                "C:\Rig\test\kaliv-voice-e01b2d1c\kaliv-samtaletest.wav",
                "C:\Rig\test\kaliv-voice-e01b2d1c\kaliv-autotest.wav"
            )) {
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $AudioPath = $candidate; break }
            }
        }
        if (-not $AudioPath -or -not (Test-Path -LiteralPath $AudioPath -PathType Leaf)) {
            throw "Test-WAV mangler. Angiv -AudioPath med den tidligere testede danske WAV."
        }
        $request = @{
            audio_base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($AudioPath))
            language = "da"
            model = $model
        } | ConvertTo-Json -Compress
        $res = Invoke-WebRequest -Uri "$base/api/v1/voice/converse/stream" -Method Post -ContentType "application/json" -Headers $auth -Body $request -TimeoutSec 900
        # PowerShell 7 returns System.Byte[] for NDJSON; decode BEFORE splitting.
        $raw = if ($res.Content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($res.Content) } else { [string]$res.Content }
        $events = @($raw -split '\r?\n' | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
        $failure = $events | Where-Object { $_.type -eq "error" } | Select-Object -First 1
        if ($failure) { throw "Voice proxy fejlede: $($failure.detail)" }
        $transcript = $events | Where-Object { $_.type -eq "transcript" } | Select-Object -First 1
        $chunk = $events | Where-Object { $_.type -eq "chunk" -and $_.audio_base64 } | Select-Object -First 1
        $done = $events | Where-Object { $_.type -eq "done" } | Select-Object -First 1
        if (-not $transcript.text -or -not $done.reply -or -not $chunk) {
            throw "Backendens stream mangler transcript/chunk/done."
        }
        $audio = [Convert]::FromBase64String($chunk.audio_base64)
        if ($audio.Length -le 44 -or [Text.Encoding]::ASCII.GetString($audio, 0, 4) -ne "RIFF") {
            throw "Backendens lydchunk er ikke gyldig WAV."
        }
        $replyPath = Join-Path $testRoot "backend-reply-$runId.wav"
        [IO.File]::WriteAllBytes($replyPath, $audio)
        Write-Host "PASS: Android-backend -> Whisper -> $model -> Piper -> WAV." -ForegroundColor Green
        Write-Host "ASR: $($transcript.text)"
        Write-Host "Svar: $($done.reply)"
        Write-Host "Lyd: $replyPath"
    }

    Write-Host ""
    Write-Host "PILOT KLAR TIL TELEFONEN (uden ADB)." -ForegroundColor Green
    Write-Host "Installer den separate Kaliv A425f test-APK fra GitHub Actions paa telefonen."
    Write-Host "Forbind testappen til: $base"
    Write-Host "Den normale Kaliv-app, port 8099 og backend 8080 er uberoerte."
    while ($true) {
        $phonePair = Get-PairCode -Base $base -AdminKey $adminKey
        Write-Host "Parringskode: $($phonePair.code) (gyldig i 5 minutter)" -ForegroundColor Yellow
        $choice = Read-Host "R + Enter = ny kode; Enter = stop piloten"
        if ($choice -ne "R" -and $choice -ne "r") { break }
    }
}
finally {
    Stop-OwnedProcess $backendProcess
    Stop-OwnedProcess $workerProcess
    if ($environmentTouched) {
        Get-ChildItem Env: | Where-Object { $_.Name -match '^(MODELRIG_|KALIV_|ALVA_)' } |
            ForEach-Object { [Environment]::SetEnvironmentVariable($_.Name, $null, "Process") }
        foreach ($name in $originalEnv.Keys) {
            [Environment]::SetEnvironmentVariable($name, $originalEnv[$name], "Process")
        }
    }
    if ($dataPath -and (Test-Path -LiteralPath $dataPath -PathType Leaf)) {
        Remove-Item -LiteralPath $dataPath -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Isoleret pilot stoppet. Produktionsportene blev ikke roert." -ForegroundColor DarkGray
}
 -or $backendExpected -ne $backendActual) {
            throw "Pilot-backendens SHA-256 matcher ikke."
        }
    }
    if (-not $LanIp) { $LanIp = Find-LanIp }
    if (-not (Test-PrivateIPv4 $LanIp)) { throw "-LanIp skal vaere en privat IPv4-adresse." }
    if (-not (Get-NetIPAddress -AddressFamily IPv4 -IPAddress $LanIp -ErrorAction SilentlyContinue)) {
        throw "$LanIp findes ikke paa riggens netkort."
    }
    foreach ($port in @($WorkerPort, $BackendPort)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "Port $port er optaget. Eksisterende processer maa ikke stoppes."
        }
    }

    $ollamaUrl = $null
    $model = $null
    foreach ($url in @("http://127.0.0.1:11434", "http://127.0.0.1:11435")) {
        try {
            $tags = Invoke-RestMethod "$url/api/tags" -TimeoutSec 5
            $available = @($tags.models | ForEach-Object { $_.name })
            $choice = @("qwen2.5-coder:7b", "gemma3:12b", "gemma4:26b") | Where-Object { $available -contains $_ } | Select-Object -First 1
            if ($choice) { $ollamaUrl = $url; $model = $choice; break }
        } catch { }
    }
    if (-not $ollamaUrl) { throw "Ingen kendt lokal Ollama-model paa 11434/11435." }

    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    $runId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") + "-" + [guid]::NewGuid().ToString("N").Substring(0,6)
    $dataPath = Join-Path $testRoot "pairing-$runId.json"
    $adminKey = New-AdminKey
    $base = "http://{0}:{1}" -f $LanIp, $BackendPort
    $workerBase = "http://127.0.0.1:{0}" -f $WorkerPort

    # Do not inherit experimental activation flags into a test worker/backend.
    Get-ChildItem Env: | Where-Object { $_.Name -match '^(MODELRIG_|KALIV_|ALVA_)' } |
        ForEach-Object { $originalEnv[$_.Name] = $_.Value }
    $environmentTouched = $true
    foreach ($name in @($originalEnv.Keys)) {
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    foreach ($name in @("KALIV_TTS_VOICE", "KALIV_TTS_VOICES_DIR", "KALIV_ASR_MODEL",
                        "KALIV_ASR_COMPUTE", "KALIV_CUDA_DLL_DIRS", "MODELRIG_VENVS_DIR")) {
        if ($originalEnv.ContainsKey($name)) {
            [Environment]::SetEnvironmentVariable($name, $originalEnv[$name], "Process")
        }
    }
    if (-not $env:MODELRIG_VENVS_DIR -and (Test-Path "C:\Rig\venvs" -PathType Container)) {
        $env:MODELRIG_VENVS_DIR = "C:\Rig\venvs"
    }
    $env:MODELRIG_WORKER_HOST = "127.0.0.1"
    $env:MODELRIG_WORKER_PORT = "$WorkerPort"
    $env:MODELRIG_HOST = $LanIp
    $env:MODELRIG_PORT = "$BackendPort"
    $env:MODELRIG_WORKER_URL = $workerBase
    $env:MODELRIG_OLLAMA_URL = $ollamaUrl
    $env:MODELRIG_GEN_MODEL = $model
    $env:MODELRIG_DATA = $dataPath
    $env:MODELRIG_ADMIN_KEY = $adminKey
    $env:KALIV_TTS_PROVIDER = "piper"
    $env:KALIV_ASR_DEVICE = "cuda"

    Write-Host ""
    Write-Host "Starter isoleret worker $workerBase og backend $base" -ForegroundColor Cyan
    Write-Host "Backend EXE: $backendExePath"
    $workerProcess = Start-Process -FilePath $workerExePath -WorkingDirectory $workerDir -PassThru -RedirectStandardOutput (Join-Path $testRoot "worker-$runId.log") -RedirectStandardError (Join-Path $testRoot "worker-$runId.err")
    $null = Wait-Ready "$workerBase/healthz" $workerProcess
    $identity = Invoke-RestMethod "$workerBase/health/full" -TimeoutSec 5
    if ($identity.build.commit_sha -ne $expectedCommit -or
        $identity.build.artifact_sha256 -ne $actualHash.ToLowerInvariant()) {
        throw "Den startede worker har forkert build-identitet."
    }

    $backendProcess = Start-Process -FilePath $backendExePath -WorkingDirectory $testRoot -PassThru -RedirectStandardOutput (Join-Path $testRoot "backend-$runId.log") -RedirectStandardError (Join-Path $testRoot "backend-$runId.err")
    $health = Wait-Ready "$base/healthz" $backendProcess
    if ($health.service -ne "modelrig-server" -or $health.version -ne "2.0.15") {
        throw "Forkert backend: service=$($health.service), version=$($health.version). Kraever 2.0.15."
    }

    $pair = Get-PairCode -Base $base -AdminKey $adminKey
    $claim = Invoke-RestMethod -Method Post -Uri "$base/api/v1/pair/claim" -ContentType "application/json" -Body (@{ code = $pair.code; device_name = "kaliv-voice-pilot-probe" } | ConvertTo-Json) -TimeoutSec 10
    if (-not $claim.token) { throw "Isoleret probe-parring gav intet token." }
    $auth = @{ Authorization = "Bearer $($claim.token)" }
    $status = Invoke-RestMethod -Uri "$base/api/v1/voice/status" -Headers $auth -TimeoutSec 10
    $tts = Invoke-RestMethod -Uri "$workerBase/voice/tts/status" -TimeoutSec 10
    if ($status.available -ne $true -or $tts.available -ne $true) {
        throw "Backendens voice/status eller workerens tts/status rapporterer utilgaengelig stemme."
    }
    Write-Host "PASS: Android-backendens Bearer-auth og voice/status -> worker." -ForegroundColor Green

    if (-not $SkipProxyVoiceProbe) {
        if (-not $AudioPath) {
            foreach ($candidate in @(
                "C:\Rig\test\kaliv-voice-e01b2d1c\kaliv-samtaletest.wav",
                "C:\Rig\test\kaliv-voice-e01b2d1c\kaliv-autotest.wav"
            )) {
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $AudioPath = $candidate; break }
            }
        }
        if (-not $AudioPath -or -not (Test-Path -LiteralPath $AudioPath -PathType Leaf)) {
            throw "Test-WAV mangler. Angiv -AudioPath med den tidligere testede danske WAV."
        }
        $request = @{
            audio_base64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($AudioPath))
            language = "da"
            model = $model
        } | ConvertTo-Json -Compress
        $res = Invoke-WebRequest -Uri "$base/api/v1/voice/converse/stream" -Method Post -ContentType "application/json" -Headers $auth -Body $request -TimeoutSec 900
        # PowerShell 7 returns System.Byte[] for NDJSON; decode BEFORE splitting.
        $raw = if ($res.Content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($res.Content) } else { [string]$res.Content }
        $events = @($raw -split '\r?\n' | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
        $failure = $events | Where-Object { $_.type -eq "error" } | Select-Object -First 1
        if ($failure) { throw "Voice proxy fejlede: $($failure.detail)" }
        $transcript = $events | Where-Object { $_.type -eq "transcript" } | Select-Object -First 1
        $chunk = $events | Where-Object { $_.type -eq "chunk" -and $_.audio_base64 } | Select-Object -First 1
        $done = $events | Where-Object { $_.type -eq "done" } | Select-Object -First 1
        if (-not $transcript.text -or -not $done.reply -or -not $chunk) {
            throw "Backendens stream mangler transcript/chunk/done."
        }
        $audio = [Convert]::FromBase64String($chunk.audio_base64)
        if ($audio.Length -le 44 -or [Text.Encoding]::ASCII.GetString($audio, 0, 4) -ne "RIFF") {
            throw "Backendens lydchunk er ikke gyldig WAV."
        }
        $replyPath = Join-Path $testRoot "backend-reply-$runId.wav"
        [IO.File]::WriteAllBytes($replyPath, $audio)
        Write-Host "PASS: Android-backend -> Whisper -> $model -> Piper -> WAV." -ForegroundColor Green
        Write-Host "ASR: $($transcript.text)"
        Write-Host "Svar: $($done.reply)"
        Write-Host "Lyd: $replyPath"
    }

    Write-Host ""
    Write-Host "PILOT KLAR TIL TELEFONEN (uden ADB)." -ForegroundColor Green
    Write-Host "Installer den separate Kaliv A425f test-APK fra GitHub Actions paa telefonen."
    Write-Host "Forbind testappen til: $base"
    Write-Host "Den normale Kaliv-app, port 8099 og backend 8080 er uberoerte."
    while ($true) {
        $phonePair = Get-PairCode -Base $base -AdminKey $adminKey
        Write-Host "Parringskode: $($phonePair.code) (gyldig i 5 minutter)" -ForegroundColor Yellow
        $choice = Read-Host "R + Enter = ny kode; Enter = stop piloten"
        if ($choice -ne "R" -and $choice -ne "r") { break }
    }
}
finally {
    Stop-OwnedProcess $backendProcess
    Stop-OwnedProcess $workerProcess
    if ($environmentTouched) {
        Get-ChildItem Env: | Where-Object { $_.Name -match '^(MODELRIG_|KALIV_|ALVA_)' } |
            ForEach-Object { [Environment]::SetEnvironmentVariable($_.Name, $null, "Process") }
        foreach ($name in $originalEnv.Keys) {
            [Environment]::SetEnvironmentVariable($name, $originalEnv[$name], "Process")
        }
    }
    if ($dataPath -and (Test-Path -LiteralPath $dataPath -PathType Leaf)) {
        Remove-Item -LiteralPath $dataPath -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Isoleret pilot stoppet. Produktionsportene blev ikke roert." -ForegroundColor DarkGray
}
