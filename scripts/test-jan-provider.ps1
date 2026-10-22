param(
    [string]$BaseUrl = "http://127.0.0.1:1337/v1",
    [string]$Model = "",
    [string]$ApiKey = "",
    [switch]$SetModelRigEnvironment
)

$ErrorActionPreference = "Stop"
$BaseUrl = $BaseUrl.TrimEnd("/")

$headers = @{}
if ($ApiKey) {
    $headers["Authorization"] = "Bearer $ApiKey"
}

Write-Host "Jan / OpenAI-compatible smoke test"
Write-Host "  endpoint: $BaseUrl"

try {
    $models = Invoke-RestMethod -Method Get -Uri "$BaseUrl/models" -Headers $headers -TimeoutSec 10
} catch {
    throw "Kan ikke hente $BaseUrl/models. Start Jan Local API Server (eller jan serve) først. $($_.Exception.Message)"
}

$ids = @($models.data | ForEach-Object { $_.id } | Where-Object { $_ })
if ($ids.Count -eq 0) {
    throw "Endpointet svarer, men returnerede ingen modeller."
}

if (-not $Model) {
    $Model = $ids[0]
}
if ($ids -notcontains $Model) {
    Write-Warning "Den valgte model '$Model' var ikke i /models-listen. Forsøger alligevel."
}

Write-Host "  model:    $Model"

$body = @{
    model = $Model
    stream = $false
    messages = @(
        @{
            role = "user"
            content = "Svar kun med: JAN_OK"
        }
    )
} | ConvertTo-Json -Depth 8

$reply = Invoke-RestMethod -Method Post -Uri "$BaseUrl/chat/completions" -Headers $headers -ContentType "application/json" -Body $body -TimeoutSec 600

$content = [string]$reply.choices[0].message.content
if ([string]::IsNullOrWhiteSpace($content)) {
    throw "Chat endpointet svarede uden choices[0].message.content."
}

Write-Host ""
Write-Host "PASS: Jan/OpenAI-compatible chat svarer."
Write-Host "Svar: $content"

if ($SetModelRigEnvironment) {
    $env:MODELRIG_LLM_PROVIDER = "jan"
    $env:MODELRIG_LLM_URL = $BaseUrl
    $env:MODELRIG_LLM_KEY = $ApiKey
    $env:MODELRIG_GEN_MODEL = $Model

    Write-Host ""
    Write-Host "Miljøvariabler er sat i denne PowerShell-session:"
    Write-Host "  MODELRIG_LLM_PROVIDER=jan"
    Write-Host "  MODELRIG_LLM_URL=$BaseUrl"
    Write-Host "  MODELRIG_GEN_MODEL=$Model"
    Write-Host "Ollama-variabler er ikke ændret; embeddings/RAG kan fortsat bruge Ollama."
}
