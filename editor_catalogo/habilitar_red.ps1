$ErrorActionPreference = "Stop"
$ruleName = "Editor catalogo de puestos - Puerto 8765"

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Remove-NetFirewallRule -DisplayName $ruleName
}

New-NetFirewallRule `
    -DisplayName $ruleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8765 `
    -Profile Any `
    -RemoteAddress LocalSubnet | Out-Null

Write-Host "Puerto 8765 habilitado para equipos de la subred local."
