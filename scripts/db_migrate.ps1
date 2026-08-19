param(
    [ValidateSet("upgrade", "stamp", "current", "history")]
    [string]$Action = "upgrade",
    [string]$Revision = "head"
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "common.ps1")
$paths = Ensure-ImmoAppTools
$python = Get-ImmoAppVenvPython -Kind server
$alembicConfig = Get-ImmoAppAlembicConfigPath

switch ($Action) {
    "upgrade" { & $python -m alembic -c $alembicConfig upgrade $Revision }
    "stamp" { & $python -m alembic -c $alembicConfig stamp $Revision }
    "current" { & $python -m alembic -c $alembicConfig current }
    "history" { & $python -m alembic -c $alembicConfig history --verbose }
}

if ($LASTEXITCODE -ne 0) {
    throw "Alembic command failed with exit code $LASTEXITCODE"
}
