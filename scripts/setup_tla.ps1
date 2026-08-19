param(
    [switch]$InstallJava,
    [string]$JavaHome,
    [string]$JarPath = "tools/tla/tla2tools.jar"
)

$ErrorActionPreference = "Stop"

function Resolve-JavaHome {
    param([string]$Preferred)
    if ($Preferred -and (Test-Path (Join-Path $Preferred "bin\\java.exe"))) {
        return (Resolve-Path $Preferred).Path
    }

    $candidates = @(
        "C:\\Program Files\\Eclipse Adoptium",
        "C:\\Program Files\\Java"
    )
    foreach ($root in $candidates) {
        if (-not (Test-Path $root)) { continue }
        $javaExe = Get-ChildItem $root -Recurse -Filter java.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\bin\\java.exe$" } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($javaExe) {
            return $javaExe.Directory.Parent.FullName
        }
    }
    return $null
}

$resolvedJavaHome = Resolve-JavaHome -Preferred $JavaHome
if (-not $resolvedJavaHome) {
    if (Get-Command java -ErrorAction SilentlyContinue) {
        $resolvedJavaHome = Resolve-JavaHome -Preferred $null
    }
}

if (-not $resolvedJavaHome -and $InstallJava) {
    Write-Host "Installing Temurin JDK 21 via winget..." -ForegroundColor Yellow
    & winget install -e --id EclipseAdoptium.Temurin.21.JDK --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "winget Java installation failed with exit code $LASTEXITCODE"
    }
    $resolvedJavaHome = Resolve-JavaHome -Preferred $null
}

if (-not $resolvedJavaHome) {
    throw "Unable to locate Java home. Pass -JavaHome explicitly."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$jarAbsPath = if ([System.IO.Path]::IsPathRooted($JarPath)) {
    $JarPath
} else {
    Join-Path $repoRoot $JarPath
}
$jarDir = Split-Path -Parent $jarAbsPath
if (-not (Test-Path $jarDir)) {
    New-Item -ItemType Directory -Path $jarDir -Force | Out-Null
}

if (-not (Test-Path $jarAbsPath)) {
    Write-Host "Downloading tla2tools.jar..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar" -OutFile $jarAbsPath
}

$jarAbsPath = (Resolve-Path $jarAbsPath).Path

$env:JAVA_HOME = $resolvedJavaHome
$env:TLA_TOOLS_JAR = $jarAbsPath
if ($env:Path -notmatch [regex]::Escape((Join-Path $resolvedJavaHome "bin"))) {
    $env:Path = (Join-Path $resolvedJavaHome "bin") + ";" + $env:Path
}

setx JAVA_HOME $resolvedJavaHome | Out-Null
setx TLA_TOOLS_JAR $jarAbsPath | Out-Null

Write-Host "TLC setup complete." -ForegroundColor Green
Write-Host "JAVA_HOME=$resolvedJavaHome"
Write-Host "TLA_TOOLS_JAR=$jarAbsPath"
Write-Host "Open a new terminal to use persisted env vars." -ForegroundColor Cyan
