# Voice ASR cold/warm comparison. Read-only calls to TEST worker 8100.
# Run immediately after restarting 8100 to capture a first-turn measurement.
param(
  [string]$BaseUrl = "http://127.0.0.1:8100",
  [string]$AudioPath = "C:\Users\an001\Desktop\voice test\turn-01.m4a",
  [string]$OutputDir = "C:\Rig\voice-asr-latency",
  [int]$Runs = 5
)
$ErrorActionPreference = "Stop"
if ($Runs -lt 2 -or $Runs -gt 20) { throw "Runs must be between 2 and 20" }
$uri = [Uri]$BaseUrl
if ($uri.Scheme -ne "http" -or $uri.Host -notin @("127.0.0.1","localhost") -or $uri.Port -ne 8100) {
  throw "Safety guard: only localhost port 8100 is supported"
}
if (-not (Test-Path -LiteralPath $AudioPath -PathType Leaf)) { throw "Missing audio: $AudioPath" }
$health = Invoke-RestMethod "$BaseUrl/healthz" -TimeoutSec 10
if ($health.status -ne "ok") { throw "Test worker not healthy" }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$rows = @()
for ($i = 1; $i -le $Runs; $i++) {
  $out = Join-Path $OutputDir "$stamp-turn-$i"
  New-Item -ItemType Directory -Path $out -Force | Out-Null
  $body = @{path=$AudioPath;language="da";model="gemma4:26b";out_dir=$out} | ConvertTo-Json
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $result = Invoke-RestMethod -Uri "$BaseUrl/voice/converse" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 180
  $sw.Stop()
  $rows += [PSCustomObject]@{
    Turn=$i
    TotalSeconds=[math]::Round($sw.Elapsed.TotalSeconds,2)
    ASRSeconds=$result.timings.asr_s
    FirstAudioSeconds=$result.timings.to_first_audio_from_request_s
    TextPresent=([bool]$result.transcript)
    AudioChunks=@($result.chunks).Count
  }
}
$csv = Join-Path $OutputDir "$stamp-metrics.csv"
$rows | Export-Csv -Path $csv -NoTypeInformation -Encoding utf8
$rows | Format-Table -AutoSize
$warm = @($rows | Select-Object -Skip 1)
$avg = ($warm | Measure-Object -Property ASRSeconds -Average).Average
[PSCustomObject]@{
  FirstASRSeconds=$rows[0].ASRSeconds
  WarmASRMeanSeconds=[math]::Round($avg,2)
  CSV=$csv
  Note="This does not prove prewarm completed; correlate with worker startup logs."
} | Format-List
