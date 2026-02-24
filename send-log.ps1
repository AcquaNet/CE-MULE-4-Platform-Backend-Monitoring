param(
    [Parameter(Mandatory=$true)]
    [string]$TenantId,

    [Parameter(Mandatory=$false)]
    [string]$Level = "INFO",

    [Parameter(Mandatory=$false)]
    [string]$Message = "Test log message",

    [Parameter(Mandatory=$false)]
    [string]$AuthToken = "8fcrQrMcOyWbn6nJdoFzkTpXQGyOHMJw7qcfUotk2v8="
)

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
    Write-Host "Make sure APISIX and Logstash are running." -ForegroundColor Yellow
}
