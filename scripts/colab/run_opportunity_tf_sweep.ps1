# Sequential Colab CPU sweep of the opportunity ensemble across TF x horizon.
[CmdletBinding()]
param(
    [string]$Distro = "Ubuntu-24.04",
    [string[]]$Timeframes = @("30m", "1h", "2h", "4h", "6h"),
    [int[]]$Horizons = @(24, 48),
    [int]$TimeoutSec = 28800,
    [string]$SummaryName = "opportunity_tf_htf_h24_h48_summary.json"
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
    foreach ($horizon in $Horizons) {
        $cell = "opportunity_${tf}_h${horizon}"
        $relPatched = "scripts/colab/_tf_sweep_tmp/transformer_btcusd_${cell}.ipynb"
        $patched = Join-Path $repoRoot $relPatched
        $zip = Join-Path $repoRoot "export\${cell}.zip"
        $dest = Join-Path $repoRoot "export\${cell}"
        if (Test-Path $zip) {
            Write-Host "=== skip $cell (zip already exists) ==="
            if (-not (Test-Path (Join-Path $dest "eval_report.json"))) {
                New-Item -ItemType Directory -Force -Path $dest | Out-Null
                Expand-Archive -Path $zip -DestinationPath $dest -Force
                Write-Host "Unzipped $zip -> $dest"
            }
            continue
        }
        Write-Host "=== $cell ==="
        & python $patcher $srcNotebook $patched $tf $horizon
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to patch notebook for $cell"
        }
        & powershell -File $cli --gpu none --session $cell --notebook $relPatched --bundle-dir $cell --stop-existing --timeout $TimeoutSec
        if ($LASTEXITCODE -ne 0) {
            throw "Colab run failed for $cell (exit $LASTEXITCODE)"
        }
        if (-not (Test-Path $zip)) {
            throw "Missing export zip $zip"
        }
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Expand-Archive -Path $zip -DestinationPath $dest -Force
        Write-Host "Unzipped $zip -> $dest"
    }
}

$horizonArgs = @()
foreach ($horizon in $Horizons) {
    $horizonArgs += "$horizon"
}
& python $compare --export-dir (Join-Path $repoRoot "export") --tfs @Timeframes --horizons @horizonArgs --output (Join-Path $repoRoot "export\$SummaryName")
exit $LASTEXITCODE
