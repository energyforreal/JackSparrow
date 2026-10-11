# Sequential Colab CPU sweep of the opportunity ensemble across timeframes.
[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu-24.04",
    [string[]]$Timeframes = @("10m", "5m", "15m", "30m", "1h"),
    [int]$TimeoutSec = 28800
)

$ErrorActionPreference = "Stop"
$env:WSL_UTF8 = "1"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..\..")).Path
$srcNotebook = Join-Path $scriptDir "transformer_btcusd_opportunity_10m.ipynb"
$cli = Join-Path $scriptDir "run_colab_cli.ps1"
$patcher = Join-Path $scriptDir "patch_opportunity_resolution.py"
$compare = Join-Path $scriptDir "compare_opportunity_tf_sweep.py"
$tmpDir = Join-Path $scriptDir "_tf_sweep_tmp"

if (-not (Test-Path $srcNotebook)) {
    throw "Notebook not found: $srcNotebook"
}

New-Item -ItemType Directory -Force -Path $tmpDir | Out-Null
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "python not found on PATH (needed to patch the notebook per TF)"
}

foreach ($tf in $Timeframes) {
    $relPatched = "scripts/colab/_tf_sweep_tmp/transformer_btcusd_opportunity_$tf.ipynb"
    $patched = Join-Path $repoRoot $relPatched
    Write-Host "=== opportunity $tf ==="
    & python $patcher $srcNotebook $patched $tf
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to patch notebook for $tf"
    }
    & powershell -File $cli --gpu none --session "opportunity-$tf" --notebook $relPatched --bundle-dir "opportunity_$tf" --stop-existing --timeout $TimeoutSec
    if ($LASTEXITCODE -ne 0) {
        throw "Colab run failed for $tf (exit $LASTEXITCODE)"
    }
    $zip = Join-Path $repoRoot "export\opportunity_$tf.zip"
    $dest = Join-Path $repoRoot "export\opportunity_$tf"
    if (-not (Test-Path $zip)) {
        throw "Missing export zip $zip"
    }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Expand-Archive -Path $zip -DestinationPath $dest -Force
    Write-Host "Unzipped $zip -> $dest"
}

& python $compare --export-dir (Join-Path $repoRoot "export") --tfs @Timeframes
exit $LASTEXITCODE
