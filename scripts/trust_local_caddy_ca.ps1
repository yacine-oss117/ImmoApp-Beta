param()

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")

function Get-LocalCaddyRootCertPath {
    $appDataRoot = Get-ImmoAppAppDataRoot
    return (Join-Path $appDataRoot "data\caddy\data\caddy\pki\authorities\local\root.crt")
}

$certPath = Get-LocalCaddyRootCertPath
if (-not (Test-Path $certPath)) {
    throw "Local Caddy root certificate not found at $certPath. Start the stack app path first so Caddy can generate it."
}

$cert = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($certPath)
$thumbprint = $cert.Thumbprint
$existing = Get-ChildItem Cert:\CurrentUser\Root | Where-Object { $_.Thumbprint -eq $thumbprint }
if ($existing) {
    Write-Host "Local Caddy root CA is already trusted for the current user." -ForegroundColor Green
    exit 0
}

Import-Certificate -FilePath $certPath -CertStoreLocation Cert:\CurrentUser\Root | Out-Null
Write-Host "Trusted local Caddy root CA for the current user." -ForegroundColor Green
Write-Host "HTTPS endpoints such as https://localhost should now validate in this Windows profile." -ForegroundColor Green
