param(
    [string]$BackendBaseUrl = "http://127.0.0.1:8000",
    [string]$EnvPath = ""
)

if (-not $EnvPath) {
    $repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $EnvPath = Join-Path $repoRoot ".env"
}

if (-not (Test-Path $EnvPath)) {
    throw "Env file not found at $EnvPath"
}

$tokenLine = Get-Content $EnvPath | Where-Object { $_ -match '^FACTBOOK_SYNC_TOKEN=' } | Select-Object -First 1
if (-not $tokenLine) {
    throw "FACTBOOK_SYNC_TOKEN is missing in $EnvPath"
}

$token = $tokenLine.Substring("FACTBOOK_SYNC_TOKEN=".Length).Trim()
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "FACTBOOK_SYNC_TOKEN is empty in $EnvPath"
}

$uri = "$($BackendBaseUrl.TrimEnd('/'))/api/factbook/sync/daily"
$headers = @{
    "x-factbook-token" = $token
    "Content-Type" = "application/json"
}
$body = @{ dry_run = $false } | ConvertTo-Json -Compress

$response = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -Body $body -TimeoutSec 900
$response | ConvertTo-Json -Depth 8
