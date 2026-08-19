param(
    [string]$OutputDir = "tools/security/sbom"
)

$ErrorActionPreference = "Stop"

function Resolve-Python([string]$kind) {
    $candidate = "C:\ProgramData\ImmoApp\venvs\immoapp-$kind-py314\Scripts\python.exe"
    if (Test-Path $candidate) {
        return $candidate
    }
    return "python"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$serverPython = Resolve-Python "server"
$clientPython = Resolve-Python "client"

$serverReq = Join-Path $OutputDir "server_requirements.txt"
$clientReq = Join-Path $OutputDir "client_requirements.txt"
$serverSbom = Join-Path $OutputDir "server.cyclonedx.json"
$clientSbom = Join-Path $OutputDir "client.cyclonedx.json"

Write-Host "[SBOM] Exporting frozen dependencies..."
& $serverPython -m pip freeze | Out-File -FilePath $serverReq -Encoding ascii
& $clientPython -m pip freeze | Out-File -FilePath $clientReq -Encoding ascii

Write-Host "[SBOM] Generating CycloneDX JSON..."
& $serverPython -m cyclonedx_py requirements $serverReq -o $serverSbom
& $clientPython -m cyclonedx_py requirements $clientReq -o $clientSbom

Write-Host "[SBOM] OK -> $OutputDir"
