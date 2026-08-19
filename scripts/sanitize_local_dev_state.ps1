param(
    [string]$AdminUsername = "admin",
    [string[]]$PreserveUsername = @()
)

. (Join-Path $PSScriptRoot "common.ps1")

$repoRoot = Get-ImmoAppRepoRoot
$python = Get-ImmoAppVenvPython -Kind server

$env:IMMOAPP_ALLOW_DESTRUCTIVE_LOCAL_SANITIZE = "1"
$args = @(
    (Join-Path $repoRoot "scripts\sanitize_local_dev_state.py"),
    "--force-local",
    "--admin-username",
    $AdminUsername
)
foreach ($username in $PreserveUsername) {
    if ([string]::IsNullOrWhiteSpace($username)) {
        continue
    }
    $args += @("--preserve-username", $username)
}
& $python @args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
