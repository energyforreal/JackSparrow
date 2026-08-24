# Provision Ubuntu WSL (if needed) and install the Google Colab CLI.
# Requires Windows WSL. Does not change the default distro (docker-desktop).
[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu-24.04",
    [string]$WslUser = "lohit"
)

$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = "1"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
$setupSh = Join-Path $scriptDir "setup_wsl_colab_cli.sh"

function Get-WslDistros {
    wsl -l -q | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}

if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) {
    throw "wsl.exe not found. Install WSL first: wsl --install --no-distribution"
}

$distros = @(Get-WslDistros)
if ($distros -notcontains $Distro) {
    Write-Host "Installing $Distro (this downloads Ubuntu; may take several minutes)..."
    wsl --install $Distro --no-launch --web-download
    $distros = @(Get-WslDistros)
    if ($distros -notcontains $Distro) {
        throw "Failed to install WSL distro $Distro"
    }
}

if (-not (Test-Path -LiteralPath $setupSh)) {
    throw "Missing $setupSh"
}

Write-Host "Bootstrapping Colab CLI inside $Distro as root..."
wsl -d $Distro -u root --cd $repoRoot -- `
    bash -lc "WSL_USER='$WslUser' bash scripts/colab/setup_wsl_colab_cli.sh"

Write-Host "Setting $Distro default user to $WslUser..."
wsl --manage $Distro --set-default-user $WslUser

Write-Host ""
Write-Host "Colab CLI is installed in $Distro."
Write-Host "Authenticate once (copy-paste Google OAuth code):"
Write-Host "  wsl -d $Distro -- bash -lc 'colab sessions'"
Write-Host "Then run the fused trainer:"
Write-Host "  powershell -File scripts/colab/run_colab_cli.ps1"
