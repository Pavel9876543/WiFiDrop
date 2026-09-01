$addresses = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object {
        $_.IPAddress -ne "127.0.0.1" -and
        $_.PrefixOrigin -ne "WellKnown" -and
        $_.AddressState -eq "Preferred"
    } |
    Select-Object -ExpandProperty IPAddress

$port = 8000
$envFile = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"
if (Test-Path $envFile) {
    $portLine = Get-Content $envFile | Where-Object { $_ -match '^PORT=(\d+)$' } | Select-Object -First 1
    if ($portLine -match '^PORT=(\d+)$') {
        $port = [int]$Matches[1]
    }
}

Write-Host ""
Write-Host "WiFiDrop addresses on this computer:" -ForegroundColor Cyan
if ($addresses) {
    foreach ($address in $addresses) {
        Write-Host "  http://${address}:${port}" -ForegroundColor Green
    }
} else {
    Write-Host "  No local IPv4 address found. Connect to Wi-Fi and try again." -ForegroundColor Yellow
}
Write-Host ""
