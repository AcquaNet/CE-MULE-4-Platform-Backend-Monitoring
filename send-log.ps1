param(
    [Parameter(Mandatory=$true)]
    [string]$TenantId,

    [Parameter(Mandatory=$false)]
    [string]$Level = "INFO",

    [Parameter(Mandatory=$false)]
    [string]$Message = "Test log message",

    # default: LOG_INGEST_TOKEN from the root .env (never hardcode it)
    [Parameter(Mandatory=$false)]
    [string]$AuthToken = ""
)

if (-not $AuthToken) {
    $envFile = Join-Path $PSScriptRoot ".env"
    $line = if (Test-Path $envFile) { Select-String -Path $envFile -Pattern '^LOG_INGEST_TOKEN=(.*)$' | Select-Object -First 1 }
    if (-not $line) { Write-Host "No -AuthToken and no LOG_INGEST_TOKEN in .env" -ForegroundColor Red; exit 1 }
    $AuthToken = $line.Matches[0].Groups[1].Value.Trim()
}

$timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
$correlationId = [guid]::NewGuid().ToString().Substring(0,8)

$log = @{
    application = "ce-mule-base"
    log_type = "mule"
    level = $Level
    message = $Message
    tenant_id = $TenantId
    worker_id = "demo-worker"
    environment = "demo"
    correlationId = "$TenantId-$correlationId"
    "@timestamp" = $timestamp
    auth_token = $AuthToken
} | ConvertTo-Json -Compress

Write-Host "Sending log for tenant: $TenantId" -ForegroundColor Cyan
Write-Host "Level: $Level" -ForegroundColor Gray
Write-Host "Message: $Message" -ForegroundColor Gray

try {
    $client = New-Object System.Net.Sockets.TcpClient("localhost", 9100)
    $stream = $client.GetStream()
    $writer = New-Object System.IO.StreamWriter($stream)
    $writer.WriteLine($log)
    $writer.Flush()
    $client.Close()
    Write-Host "Log sent successfully!" -ForegroundColor Green
} catch {
    Write-Host "Error sending log: $_" -ForegroundColor Red
    Write-Host "Make sure APISIX and Fluent Bit (logging profile) are running." -ForegroundColor Yellow
}
