"""Insert state-head training cells into jacksparrow_v43_delta_india_training.ipynb."""
from __future__ import annotations

import json
from pathlib import Path

NB_PATH = Path("notebooks/jacksparrow_v43_delta_india_training.ipynb")
INSERT_MARKER = "train_state_heads_from_feature_matrix("


def _cell(code: str, cell_type: str = "code") -> dict:
    return {
        "cell_type": cell_type,
        "metadata": {},
        "source": [line + "\n" for line in code.splitlines()],
        "outputs": [],
        "execution_count": None,
    }


def _has_state_head_training(cells: list) -> bool:
    return any(INSERT_MARKER in "".join(c.get("source", [])) for c in cells)


def main() -> None:
    nb = json.loads(NB_PATH.read_text(encoding="utf-8"))
    cells = nb["cells"]

    md_state = _cell(
        "## 3b) State-intelligence heads\n\n"
        "Train regime (4-class), volatility expansion (binary), and trade-quality "
        "(triple-barrier binary) classifiers. Outputs attach to `multi_bundle.state_heads` "
        "and `metadata['state_heads']` for export.\n",
        cell_type="markdown",
    )

    state_train = _cell(
        """# State-intelligence heads (regime / vol-expansion / trade-quality)
_primary_bars = int(os.environ.get("V43_PRIMARY_EXECUTION_HORIZON_BARS", "12"))
_skip = int(os.environ.get("V43_STATE_HEAD_SKIP_BARS", str(_primary_bars)))
_vol_weights = compute_vol_sample_weights(df_feat)
_state_models, state_heads_meta = train_state_heads_from_feature_matrix(
    df_feat,
    close,
    feat_cols=feat_cols,
    validation_fraction=float(os.environ.get("V43_VALIDATION_FRACTION", "0.15")),
    rng=_train_rng,
    embargo_bars=_primary_bars,
    skip_bars=_skip if _skip > 1 else None,
    sample_weight_series=_vol_weights,
    trade_quality_forward_bars=_primary_bars,
    take_profit_pct=float(os.environ.get("V43_TRADE_QUALITY_TP", "0.012")),
    stop_loss_pct=float(os.environ.get("V43_TRADE_QUALITY_SL", "0.008")),
)
for _k, _m in _state_models.items():
    multi_bundle.set_state_head(_k, _m)
metadata["state_heads"] = state_heads_meta
metadata["training_feature_stats"] = training_feature_stats_dict(df_feat, feat_cols)
metadata["primary_execution_horizon_bars"] = _primary_bars
print(format_state_head_diagnostics(metadata))
print("State heads attached:", list(_state_models.keys()))
"""
    )

    methodology = _cell(
        """# Methodology hardening: importance, correlation, drift diagnostics
_corr = feature_correlation_report(df_feat, feat_cols, threshold=0.85)
print(f"Feature pairs with |Spearman| >= {_corr['threshold']}: {len(_corr['pairs_flagged'])}")
for _p in _corr["pairs_flagged"][:12]:
    print(f"  {_p['a']} vs {_p['b']}: {_p['spearman']:.3f}")

_importances = extract_head_importances(multi_bundle, top_k=15)
for _hkey, _imp in _importances.items():
    print(f"\\n{_hkey} — top features (gain):")
    for _feat, _gain in sorted(_imp.items(), key=lambda x: -x[1])[:15]:
        print(f"  {_feat}: {_gain:.2f}")

_drift_feats = ["vol_regime", "funding_zscore", "basis_zscore", "adx_14", "hurst_60"]
try:
    import matplotlib.pyplot as plt

    for _df in _drift_feats:
        if _df not in df_feat.columns:
            continue
        s = pd.to_numeric(df_feat[_df], errors="coerce")
        rm = s.rolling(8640, min_periods=200).mean()
        rs = s.rolling(8640, min_periods=200).std()
        plt.figure(figsize=(10, 2))
        plt.plot(rm.values[-5000:], label="rolling_mean_30d")
        plt.plot(rs.values[-5000:], label="rolling_std_30d", alpha=0.7)
        plt.title(_df)
        plt.legend()
        plt.tight_layout()
        plt.show()
except ImportError:
    print("matplotlib not available — skip drift plots")
"""
    )

    kpi_cell = _cell(
        """# State-head + trend_1h acceptance KPIs (Run 11 targets)
from feature_store.jacksparrow_v43_labels import build_forward_labels
from feature_store.jacksparrow_v43_multihead import V43_HORIZON_KEY_TO_BARS
from agent.core.v43_signal_gates import gate5_long_edge_metrics

_sh = metadata.get("state_heads") or {}
print("=== State-head KPIs (targets: regime BA>=0.60, vol AUC>=0.58, quality AUC>=0.56) ===")
print(f"regime balanced_accuracy: {_sh.get('regime', {}).get('balanced_accuracy')}")
print(f"vol_expansion AUC: {_sh.get('vol_expansion', {}).get('validation_auc')}")
print(f"trade_quality AUC: {_sh.get('trade_quality', {}).get('validation_auc')}")

_trend_key = "trend_1h"
_trend = metadata["horizons"][_trend_key]
_vm = _trend["validation_metrics"]
_fb = int(V43_HORIZON_KEY_TO_BARS[_trend_key])
_y = build_forward_labels(close, _fb)
_work = df_feat[feat_cols].copy()
_work["target"] = _y.values
_work = _work.dropna(subset=["target"])
_val_frac = float(os.environ.get("V43_VALIDATION_FRACTION", "0.15"))
_val_start = int(len(_work) * (1.0 - _val_frac))
_val = _work.iloc[_val_start:]
_ens = multi_bundle.get_head(_fb)
_stack = _vm.get("inference_path", "regressor_mean")
_pred = np.asarray(
    _ens.predict(
        _val[feat_cols].values,
        X_df=_val[feat_cols],
        inference_stack=_stack,
    ),
    dtype=np.float64,
).ravel()
_dt = float(_vm.get("dynamic_threshold") or 0.005)
_long_mask = _pred > _dt
_rtc = float(metadata.get("runtime_cost_assumptions", {}).get("round_trip_cost_pct", 0.0016))
_yv = _val["target"].values
_long_net_hit = float((_yv[_long_mask] - _rtc > 0).mean()) if _long_mask.any() else None
_g5_pass = float(
    sum(gate5_long_edge_metrics(float(p), _dt).passes for p in _pred[_long_mask])
    / max(1, int(_long_mask.sum()))
) if _long_mask.any() else 0.0
print(f"trend_1h gate-5 long pass rate (target >=12%): {_g5_pass:.2%}")
print(f"trend_1h net long hit rate (target >=46%): {_long_net_hit}")
"""
    )

    if not _has_state_head_training(cells):
        insert_at = 19
        cells[insert_at:insert_at] = [md_state, state_train, methodology, kpi_cell]
        print(f"Inserted 4 cells at index {insert_at}")

    # Cell 18: primary horizon messaging
    for cell in cells:
        src = "".join(cell.get("source", []))
        if "train_multihead_from_feature_matrix(" in src and "primary_ensemble" in src:
            src = src.replace(
                "validation_metrics = metadata[\"horizons\"][\"scalp_10m\"][\"validation_metrics\"]",
                '_primary_bars = int(os.environ.get("V43_PRIMARY_EXECUTION_HORIZON_BARS", "12"))\n'
                '_primary_key = {2: "scalp_10m", 6: "intraday_30m", 12: "trend_1h", 24: "swing_2h"}.get(_primary_bars, "trend_1h")\n'
                'validation_metrics = metadata["horizons"][_primary_key]["validation_metrics"]',
            )
            src = src.replace(
                "primary_ensemble = multi_bundle.get_head(2)  # scalp_10m primary",
                "primary_ensemble = multi_bundle.get_head(_primary_bars)",
            )
            src = src.replace(
                'print("Primary execution head (scalp_10m / 2 bars) validation_corr:", validation_metrics.get("validation_corr"))',
                'print(f"Primary execution head ({_primary_key} / {_primary_bars} bars) validation_corr:", validation_metrics.get("validation_corr"))',
            )
            cell["source"] = [line + "\n" for line in src.splitlines()]
            break

    nb["cells"] = cells
    NB_PATH.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print("Patched", NB_PATH, "total cells:", len(cells))


if __name__ == "__main__":
    main()
