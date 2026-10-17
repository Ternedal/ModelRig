# Read-only, single-shot ModelRig resource snapshot.
# PowerShell 7; no prompts, secrets, service changes or persistent files.
param(
    [ValidatePattern('^http://127[.]0[.]0[.]1:[0-9]{1,5}$')]
    [string]$OllamaUrl = 'http://127.0.0.1:11435'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$stamp = [DateTimeOffset]::UtcNow.ToString('o')
$gpuRows = @()
$gpuError = $null
try {
    $raw = @(& nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu,power.draw --format=csv,noheader,nounits 2>&1)
    if ($LASTEXITCODE -ne 0) { throw 'nvidia-smi returned a nonzero exit code' }
    foreach ($line in $raw) {
        $parts = @(([string]$line).Split(',') | ForEach-Object { $_.Trim() })
        if ($parts.Count -ne 5) { throw 'Unexpected nvidia-smi CSV format' }
        $gpuRows += [ordered]@{
            index = $parts[0]; memory_used_mib = $parts[1]
            memory_total_mib = $parts[2]; utilization_pct = $parts[3]
            power_w = $parts[4]
        }
    }
} catch { $gpuError = $_.Exception.Message }
$models = @()
$ollamaError = $null
try {
    $response = Invoke-RestMethod -Method Get -Uri "$OllamaUrl/api/ps" -TimeoutSec 10
    foreach ($model in @($response.models)) {
        if ($null -eq $model) { continue }
        # Names only: never include paths, tokens, prompts or model metadata.
        $models += [string]$model.name
    }
} catch { $ollamaError = $_.Exception.Message }
$ram = $null
try {
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
    $ram = [ordered]@{
        total_mib = [math]::Round([double]$os.TotalVisibleMemorySize / 1024, 1)
        free_mib = [math]::Round([double]$os.FreePhysicalMemory / 1024, 1)
    }
} catch { }
[ordered]@{
    schema = 'modelrig-resource-snapshot/v1'
    captured_utc = $stamp
    ollama_endpoint = $OllamaUrl
    loaded_models = $models
    gpus = $gpuRows
    gpu_error = $gpuError
    ollama_error = $ollamaError
    ram = $ram
    note = 'One-shot observation only; no benchmark or release qualification'
} | ConvertTo-Json -Depth 6
