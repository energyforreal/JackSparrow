# MSO v50 Colab validation checklist

After pushing `MAJOR-REWORK-2`, run the full training notebook on Colab (not `MSO_COLAB_QUICK`).

## Environment (defaults after production-readiness changes)

```python
# Optional overrides — defaults are production-oriented
# os.environ["MSO_GATE_SCOPE"] = "policy"      # default
# os.environ["MSO_BLOCK_EXPORT_ON_FAIL"] = "true"  # default
# os.environ["MSO_CALIBRATE"] = "false"        # default
# os.environ["MSO_USE_CLASS_WEIGHT"] = "false" # default
# os.environ["MSO_TREND_3CLASS"] = "true"      # default
```

## Verify clone

```python
!git -C /content/trading-agent log -1 --oneline
!grep -n "MSO_GATE_SCOPE\|MSO_USE_CLASS_WEIGHT\|collapse_trend" \
    /content/trading-agent/scripts/generate_mso_notebook.py \
    /content/trading-agent/feature_store/jacksparrow_mso_labels.py | head -20
```

## Pass criteria (policy scope)

| Check | Pass |
|-------|------|
| Export | No `RuntimeError`; `export_gate_passed: true` in metadata |
| Scope | `export_gate_scope: policy` |
| liquidity | STOP_HUNT or LIQ_SWEEP val recall > 0 |
| trend | 3-class BULL/RANGE/BEAR; f1_macro ≥ 0.50, bal_acc ≥ 0.35 |
| breakout | bal_acc ≥ 0.35; pred_mode not stuck on BREAKOUT_EXHAUSTION |
| Decode | Agent unit tests pass locally (`test_mso_shims.py`) |

## Deploy

1. Download `jacksparrow_mso_v50_bundle.zip` from Colab export cell.
2. Copy `metadata_mso_v50.json` + `model_artifact_mso_v50.pkl` into `MODEL_DIR`.
3. Enable with `MSO_MODEL_ENABLED=true`; use `MSO_SHADOW_MODE=true` for paper validation first.

Do **not** set `MSO_BLOCK_EXPORT_ON_FAIL=false` for production bundles.
