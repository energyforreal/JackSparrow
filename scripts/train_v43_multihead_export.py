#!/usr/bin/env python3
"""Train and export JackSparrow v43 multi-head intraday bundle (2/6/12/24 bars).

Usage (from repo root):
  python scripts/train_v43_multihead_export.py --output-dir agent/model_storage/JackSparrow_v43_models_BTCUSD

Requires OHLCV frames or a pre-built feature matrix CSV. For Colab/full retrain,
use notebooks/jacksparrow_v43_delta_india_training.ipynb which calls the same
``train_multihead_from_feature_matrix`` entrypoint.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import joblib  # noqa: E402
import pandas as pd  # noqa: E402

from feature_store.jacksparrow_v43_contract import V43_CANONICAL_FEATURES  # noqa: E402
from feature_store.jacksparrow_v43_multihead import validate_multihead_export_gates  # noqa: E402
from feature_store.jacksparrow_v43_train_multihead import (  # noqa: E402
    artifact_dict_from_bundle,
    train_multihead_from_feature_matrix,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export v43 multi-head bundle")
    p.add_argument(
        "--output-dir",
        type=Path,
        default=_REPO / "agent" / "model_storage" / "JackSparrow_v43_models_BTCUSD",
        help="Directory for metadata_v43.json and model_artifact_v43.pkl",
    )
    p.add_argument(
        "--feature-csv",
        type=Path,
        default=None,
        help="Optional CSV with canonical features + close column",
    )
    p.add_argument(
        "--min-rows",
        type=int,
        default=2000,
        help="Minimum rows required after dropna (synthetic/dev only below 500 per head)",
    )
    p.add_argument(
        "--strict-export-gates",
        action="store_true",
        help="Enforce per-horizon meta_auc/corr gates (use with real feature CSV)",
    )
    return p.parse_args()


def _synthetic_feature_matrix(n_rows: int = 2500) -> tuple[pd.DataFrame, pd.Series]:
    """Minimal synthetic matrix for CI/dev bundle smoke (not for production trading)."""
    import numpy as np

    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n_rows, freq="5min", tz="UTC")
    data = {c: rng.normal(0, 1, n_rows) for c in V43_CANONICAL_FEATURES}
    close = pd.Series(100_000 + np.cumsum(rng.normal(0, 50, n_rows)), index=idx)
    df = pd.DataFrame(data, index=idx)
    return df, close


def main() -> int:
    args = _parse_args()
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.feature_csv and args.feature_csv.is_file():
        raw = pd.read_csv(args.feature_csv)
        if "close" not in raw.columns:
            raise SystemExit("--feature-csv must include a 'close' column")
        close = raw["close"].astype(float)
        df_feat = raw[list(V43_CANONICAL_FEATURES)]
    else:
        print("No --feature-csv; using synthetic feature matrix (dev/CI only).")
        df_feat, close = _synthetic_feature_matrix(max(args.min_rows, 2500))

    use_cost_aware = bool(args.feature_csv and args.feature_csv.is_file())
    bundle, metadata = train_multihead_from_feature_matrix(
        df_feat,
        close,
        feat_cols=list(V43_CANONICAL_FEATURES),
        cost_aware_labels=use_cost_aware,
    )
    metadata["model_name"] = metadata.get("model_name") or "jacksparrow_v43_BTCUSD"
    metadata["version_tag"] = metadata.get("version") or "v43"

    class _StubFE:
        columns = list(V43_CANONICAL_FEATURES)

        def transform(self, *a, **k):
            raise RuntimeError("use agent feature engineer at runtime")

    artifact = artifact_dict_from_bundle(bundle, _StubFE())
    meta_path = out_dir / "metadata_v43.json"
    art_path = out_dir / "model_artifact_v43.pkl"
    if args.strict_export_gates:
        validate_multihead_export_gates(metadata, strict=True)
        print("Export gates: PASS (strict)")
    else:
        failures = validate_multihead_export_gates(metadata, strict=False)
        if failures:
            print("WARNING export gates not met (dev/synthetic OK):")
            for f in failures:
                print(f"  - {f}")

    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    joblib.dump(artifact, art_path)
    print(f"Wrote {meta_path}")
    print(f"Wrote {art_path}")
    print(f"Horizons: {list(metadata.get('horizons', {}).keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
