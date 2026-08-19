"""Validate a per-TF transformer bundle before copying into agent/model_storage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_COL,
    CONTINUOUS_LABEL_COLS,
    FEATURE_CONTRACT_VERSION,
    ONNX_OUTPUT_NAMES,
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
    feature_cols_for_resolution,
    scale_period,
)
from feature_store.transformer_btcusd.features import (
    assemble_raw_frame,
    build_feature_matrix,
    validate_feature_columns,
)
from feature_store.transformer_btcusd.inference import (
    build_candle_class_window,
    build_continuous_window,
    require_onnx_output_names,
    resolve_feature_config,
)


def validate_bundle(bundle_dir: Path) -> dict[str, object]:
    """Run contract, feature, and ONNX shape checks on a bundle directory."""
    bundle_dir = bundle_dir.resolve()
    meta_path = bundle_dir / TRANSFORMER_METADATA_FILENAME
    if not meta_path.is_file():
        raise FileNotFoundError(f"Missing {TRANSFORMER_METADATA_FILENAME} in {bundle_dir}")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    feature_config = resolve_feature_config(bundle_dir)
    onnx_name = str(meta.get("onnx_filename") or "")
    onnx_path = bundle_dir / onnx_name
    if not onnx_path.is_file():
        raise FileNotFoundError(f"Missing ONNX file: {onnx_path}")

    bundle_contract = str(feature_config.get("feature_contract_version") or "")
    contract_ok = bundle_contract == FEATURE_CONTRACT_VERSION
    window_len = int(feature_config.get("window_len") or 128)
    resolution_minutes = int(meta.get("resolution_minutes") or 15)

    import numpy as np
    import pandas as pd

    warmup_bars = scale_period(96, resolution_minutes) + window_len + 50
    n = max(2000, warmup_bars)
    ts = pd.date_range("2024-01-01", periods=n, freq=f"{resolution_minutes}min", tz="UTC")
    close = 50000 + np.cumsum(np.random.default_rng(0).normal(0, 20, n))
    ohlcv = pd.DataFrame(
        {
            "time": ts,
            "open": close - 5,
            "high": close + 20,
            "low": close - 20,
            "close": close,
            "volume": np.full(n, 100.0),
        }
    )
    fund = pd.DataFrame(
        {"time": ts[::2], "funding_rate": np.linspace(0.0001, 0.0002, len(ts[::2]))}
    )
    oi = pd.DataFrame(
        {"time": ts[1::2], "open_interest": np.linspace(1e6, 1.1e6, len(ts[1::2]))}
    )
    feat_df = build_feature_matrix(
        assemble_raw_frame(ohlcv, funding_df=fund, oi_df=oi),
        resolution_minutes=resolution_minutes,
        dropna=True,
    )
    resolution = str(meta.get("resolution") or "15m")
    feature_cols = list(
        feature_config.get("feature_cols") or feature_cols_for_resolution(resolution)
    )
    validate_feature_columns(
        feat_df, require_finite_closed_bar=True, feature_cols=feature_cols
    )
    values = feat_df[list(feature_cols)].values.astype(np.float32)
    cont_window = build_continuous_window(values, window_len=window_len)
    cat_window = build_candle_class_window(
        feat_df[CANDLE_CLASS_COL].values, window_len=window_len
    )

    import onnxruntime as ort

    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    output_names = [o.name for o in sess.get_outputs()]
    require_onnx_output_names(output_names)
    named = {
        name: arr
        for name, arr in zip(
            output_names,
            sess.run(
                None,
                {
                    "continuous_features": cont_window,
                    "candle_class_ids": cat_window,
                },
            ),
        )
    }
    continuous = named["continuous_pred"]
    regime = named["regime_logits"]
    label_cols = list(feature_config.get("continuous_label_cols") or [])
    if list(label_cols) != list(CONTINUOUS_LABEL_COLS):
        raise RuntimeError(
            f"continuous_label_cols mismatch: bundle={label_cols} "
            f"runtime={list(CONTINUOUS_LABEL_COLS)}"
        )
    if continuous.shape[-1] != len(CONTINUOUS_LABEL_COLS):
        raise RuntimeError(
            f"ONNX continuous_pred last dim {continuous.shape[-1]} != "
            f"{len(CONTINUOUS_LABEL_COLS)}"
        )
    export_quality = meta.get("export_quality") or {}

    return {
        "bundle_dir": str(bundle_dir),
        "contract_ok": contract_ok,
        "bundle_contract_version": bundle_contract,
        "runtime_contract_version": FEATURE_CONTRACT_VERSION,
        "onnx_output_names": list(ONNX_OUTPUT_NAMES),
        "onnx_continuous_shape": list(continuous.shape),
        "onnx_regime_shape": list(regime.shape),
        "onnx_structure_shape": list(named["structure_outcome_logits"].shape),
        "onnx_future_candle_shape": list(named["future_candle_logits"].shape),
        "expected_continuous_outputs": len(CONTINUOUS_LABEL_COLS),
        "export_quality_tier": export_quality.get("tier"),
        "export_quality_warnings": export_quality.get("warnings") or [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate transformer ONNX bundle")
    parser.add_argument("bundle_dir", type=Path, help="Path to JackSparrow_Transformer_BTCUSD_*")
    args = parser.parse_args()
    report = validate_bundle(args.bundle_dir)
    print(json.dumps(report, indent=2))
    if not report["contract_ok"]:
        raise SystemExit(
            f"Feature contract mismatch: bundle={report['bundle_contract_version']} "
            f"runtime={report['runtime_contract_version']}"
        )


if __name__ == "__main__":
    main()
