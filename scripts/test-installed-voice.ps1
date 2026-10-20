#requires -Version 5.1
<#
.SYNOPSIS
Exercise TTS and CUDA ASR in the installed, published v2.0.17 worker.
.DESCRIPTION
Run on the rig after updating. Requires no Python, SDK, git, tokens or restart.
Uses the current voice configuration; the first ASR request can load/download
the configured model. Writes a synthetic WAV and diagnostic JSON under RigRoot.
This is NOT the human-recording baseline or Android/V1 acceptance evidence.
#>
[CmdletBinding()]
param(
    [string]$RigRoot = 'C:\Rig\ModelRig',
    [ValidateRange(1, 65535)][int]$ServerPort = 8080,
    [ValidateRange(1, 65535)][int]$WorkerPort = 8099,
    [ValidateRange(1, 1800)][int]$InferenceTimeoutSeconds = 300
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http

# Published artifact identity, not the HEAD of the checkout containing this tool.
$expectedVersion = '2.0.17'
$expectedCommit = '3d52cc97735b9572225cc5776d9ebc16656951b6'
$expectedWorkerSha = '9a7cfbaa2e69565e30fab387076d1e099d9d65173218e0cf677ce84a7f1ddea6'
$checks = New-Object 'System.Collections.Generic.List[object]'
$report = [ordered]@{
    schema = 'kaliv-installed-voice-diagnostic/v1'
    started_utc = [DateTime]::UtcNow.ToString('o')
    status = 'failed'
    stage = 'setup'
    synthetic_audio = $true
    v1_accepted = $false
    limitations = @('No microphone or Android test', 'No human-recording baseline',
        'No conversation, cancellation or latency acceptance', 'No agent activation')
    expected = [ordered]@{
        version = $expectedVersion; commit_sha = $expectedCommit
        worker_artifact_sha256 = $expectedWorkerSha
    }
    checks = $checks
}
$reportPath = $null

function Assert-Check([string]$Name, [bool]$Passed, [string]$Failure) {
    $checks.Add([ordered]@{ name = $Name; passed = $Passed })
    if (-not $Passed) { throw $Failure }
}

function Is-True($Value) {
    return ($Value -is [bool] -and $Value)
}

function Request-Json([int]$Port, [string]$Path, $Body = $null, [int]$Timeout = 30) {
    # Fixed loopback host; neither a proxy nor a redirect may move this request.
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.UseProxy = $false
    $handler.AllowAutoRedirect = $false
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($Timeout)
    $client.MaxResponseContentBufferSize = 65536
    $response = $null
    $content = $null
    try {
        $url = 'http://127.0.0.1:{0}{1}' -f $Port, $Path
        if ($null -eq $Body) {
            $response = $client.GetAsync($url).GetAwaiter().GetResult()
        } else {
            $json = ConvertTo-Json -InputObject $Body -Compress
            $content = New-Object System.Net.Http.StringContent($json, [Text.Encoding]::UTF8, 'application/json')
            $response = $client.PostAsync($url, $content).GetAwaiter().GetResult()
        }
        $raw = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if ([int]$response.StatusCode -ne 200) {
            # Preserve a bounded worker error, e.g. missing CUDA DLL / HTTP 503.
            $detail = $raw.Substring(0, [Math]::Min(400, $raw.Length))
            throw ('{0}: HTTP {1}: {2}' -f $Path, [int]$response.StatusCode, $detail)
        }
        $value = ConvertFrom-Json -InputObject $raw
        if (-not $raw.TrimStart().StartsWith('{') -or
            $null -eq $value -or $value -isnot [pscustomobject]) {
            throw "$Path did not return a JSON object"
        }
        return $value
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        if ($null -ne $content) { $content.Dispose() }
        $client.Dispose()
    }
}

function Read-Release([string]$Phase) {
    $server = Request-Json $ServerPort '/healthz'
    $worker = Request-Json $WorkerPort '/healthz'
    Assert-Check "$Phase-server" ($server.status -eq 'ok' -and
        $server.service -eq 'modelrig-server' -and $server.version -eq $expectedVersion) `
        "Server must report $expectedVersion. Finish the updater before running this check."
    Assert-Check "$Phase-worker" ($worker.status -eq 'ok' -and
        $worker.service -eq 'modelrig-worker' -and $worker.version -eq $expectedVersion) `
        "Worker must report $expectedVersion. Finish the updater before running this check."
    $health = Request-Json $WorkerPort '/health/full'
    $build = $health.build
    Assert-Check "$Phase-release-artifact" ((Is-True $build.frozen) -and
        $build.commit_sha -eq $expectedCommit -and $build.artifact_sha256 -eq $expectedWorkerSha) `
        'The running worker does not match the published v2.0.17 Windows executable.'
    Assert-Check "$Phase-voice-capabilities" ((Is-True $health.capabilities.asr) -and
        (Is-True $health.capabilities.tts)) 'The installed worker is missing ASR or TTS.'
    Assert-Check "$Phase-cuda" (Is-True $health.capabilities.cuda) `
        'The running worker cannot see CUDA. This check requires GPU ASR.'
    return [ordered]@{
        server_version = $server.version; worker_version = $worker.version
        build = $build; capabilities = $health.capabilities
    }
}

function Read-Asr([string]$Phase) {
    $asr = Request-Json $WorkerPort '/voice/asr/status'
    Assert-Check "$Phase-asr-available" (Is-True $asr.available) 'ASR is unavailable in the running worker.'
    Assert-Check "$Phase-asr-cuda" ($asr.device -ceq 'cuda') `
        'ASR is configured for a different device. No settings were changed; CPU does not pass this check.'
    return $asr
}

try {
    if (-not (Test-Path -LiteralPath $RigRoot -PathType Container)) {
        throw "RigRoot does not exist: $RigRoot"
    }
    $runName = '{0}-{1}' -f [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'), [Guid]::NewGuid().ToString('N')
    $directory = Join-Path (Join-Path ([IO.Path]::GetFullPath($RigRoot)) 'diagnostics') $runName
    [void][IO.Directory]::CreateDirectory($directory)
    $reportPath = Join-Path $directory 'installed-voice.json'
    $wavPath = Join-Path $directory 'synthetic-da.wav'
    Write-Host 'Installed v2.0.17 voice diagnostic (synthetic audio; V1 acceptance remains pending).'

    $report.stage = 'installed-release'
    $report['before'] = Read-Release 'before'
    $report['asr_before'] = Read-Asr 'before'
    $ttsStatus = Request-Json $WorkerPort '/voice/tts/status'
    Assert-Check 'tts-available' (Is-True $ttsStatus.available) 'TTS is unavailable in the running worker.'
    $report['tts_status'] = $ttsStatus

    $report.stage = 'tts-synthesis'
    Write-Host 'Synthesizing Danish audio using the current voice configuration...'
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $tts = Request-Json $WorkerPort '/voice/tts/synthesize' @{
        text = 'Hej Kaliv. Dette er en dansk lydtest. Stemmen skal virke.'
        out_path = $wavPath
    } $InferenceTimeoutSeconds
    $clock.Stop()
    $report['tts'] = $tts
    $report['tts_elapsed_ms'] = $clock.ElapsedMilliseconds
    Assert-Check 'tts-output' ($tts.out_path -eq $wavPath -and
        $tts.duration -is [ValueType] -and $tts.duration -isnot [bool] -and
        $tts.duration -gt 0 -and $tts.provider -is [string] -and
        -not [string]::IsNullOrWhiteSpace($tts.provider) -and
        (Test-Path -LiteralPath $wavPath -PathType Leaf)) 'TTS did not produce the requested non-empty WAV.'
    $wav = [IO.File]::ReadAllBytes($wavPath)
    Assert-Check 'wav-header' ($wav.Length -gt 44 -and
        [Text.Encoding]::ASCII.GetString($wav, 0, 4) -ceq 'RIFF' -and
        [Text.Encoding]::ASCII.GetString($wav, 8, 4) -ceq 'WAVE') 'TTS output is not a non-empty RIFF/WAVE file.'
    $report['audio'] = [ordered]@{
        path = $wavPath; bytes = $wav.Length
        sha256 = (Get-FileHash -LiteralPath $wavPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }

    $report.stage = 'cuda-transcription'
    Write-Host 'Transcribing the generated WAV with configured CUDA ASR (first use may load the model)...'
    $clock.Restart()
    $asr = Request-Json $WorkerPort '/voice/asr/transcribe' @{ path = $wavPath; language = 'da' } $InferenceTimeoutSeconds
    $clock.Stop()
    $report['transcription'] = $asr
    $report['asr_elapsed_ms'] = $clock.ElapsedMilliseconds
    Assert-Check 'asr-result' ($asr.text -is [string] -and -not [string]::IsNullOrWhiteSpace($asr.text) -and
        @($asr.segments).Count -gt 0 -and $asr.duration -is [ValueType] -and
        $asr.duration -isnot [bool] -and $asr.duration -gt 0) 'ASR returned no transcript, segments or positive duration.'

    $report.stage = 'post-inference-identity'
    $report['asr_after'] = Read-Asr 'after'
    Assert-Check 'asr-config-stable' ($report.asr_before.model -eq $report.asr_after.model -and
        $report.asr_before.compute_type -eq $report.asr_after.compute_type) 'ASR configuration changed during the check.'
    $report['after'] = Read-Release 'after'
    $report.status = 'diagnostic_pass'
    $report.stage = 'complete'
    Write-Host ('PASS: published v2.0.17 worker synthesized audio and transcribed it with CUDA configured. Provider: {0}' -f $tts.provider)
    Write-Host ('Transcript: {0}' -f $asr.text)
    Write-Host 'Microphone, Android, voice quality and V1 acceptance still require the physical tests.'
} catch {
    $report['error'] = $_.Exception.Message
    Write-Host ('FAIL at {0}: {1}' -f $report.stage, $report.error) -ForegroundColor Red
} finally {
    $report['finished_utc'] = [DateTime]::UtcNow.ToString('o')
    if ($null -ne $reportPath) {
        try {
            $json = ConvertTo-Json -InputObject $report -Depth 12
            [IO.File]::WriteAllText($reportPath, $json, (New-Object Text.UTF8Encoding($false)))
            Write-Host "Diagnostic: $reportPath"
        } catch {
            $report.status = 'failed'
            Write-Host ('Could not save diagnostic: {0}' -f $_.Exception.Message) -ForegroundColor Red
        }
    }
}
if ($report.status -ne 'diagnostic_pass') { exit 1 }
exit 0
