# Thin Windows trampoline: run the Colab CLI helper inside Ubuntu WSL.
[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu-24.04",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RunnerArgs
)

$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = "1"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path

if (-not (Get-Command wsl -ErrorAction SilentlyContinue)) {
    throw "wsl.exe not found. Install WSL first: wsl --install --no-distribution"
}

$distros = @(wsl -l -q | ForEach-Object { $_.Trim() } | Where-Object { $_ })
if ($distros -notcontains $Distro) {
    throw "WSL distro $Distro is not installed. Run: powershell -File scripts/colab/setup_wsl_colab_cli.ps1"
}

$bashArgs = @("scripts/colab/run_colab_cli.sh")
if ($RunnerArgs) {
    $bashArgs += $RunnerArgs
}

# bash -lc so ~/.profile puts uv's ~/.local/bin on PATH.
$quoted = ($bashArgs | ForEach-Object { $_ -replace "'", "'\''" | ForEach-Object { "'$_'" } }) -join " "
wsl -d $Distro --cd $repoRoot -- bash -lc $quoted
exit $LASTEXITCODE
