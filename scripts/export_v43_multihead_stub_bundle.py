#!/usr/bin/env python3
"""Write a minimal valid multi-head metadata + artifact stub (no LGBM training).

Use for CI/dev when sklearn/lightgbm pins differ. Production bundles must use
``train_v43_multihead_export.py`` or the Colab notebook.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import numpy as np

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agent.models.v43_pickle_shims import EnsembleModel, MultiHeadBundle  # noqa: E402
from feature_store.jacksparrow_v43_contract import V43_CANONICAL_FEATURES  # noqa: E402
from feature_store.jacksparrow_v43_multihead import (  # noqa: E402
    V43_HORIZON_KEY_TO_BARS,
    V43_HORIZON_KEYS,
    V43_MULTIHEAD_ARTIFACT_FORMAT,
    V43_MULTIHEAD_MODEL_FAMILY,
)
def _stub_ensemble(threshold: float = 0.005) -> EnsembleModel:
    from sklearn.linear_model import Ridge

    m = EnsembleModel()
    m.dynamic_threshold = threshold
    m.threshold = threshold
    m._is_fitted = True
    m.feature_cols = list(V43_CANONICAL_FEATURES)
    n_feat = len(V43_CANONICAL_FEATURES)
    X0 = np.zeros((8, n_feat), dtype=np.float64)
    y0 = np.zeros(8, dtype=np.float64)
    m.rf = Ridge(alpha=1.0)
    m.rf.fit(X0, y0)
    return m


def main() -> int:
    out_dir = _REPO / "agent" / "model_storage" / "JackSparrow_v43_models_BTCUSD"
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture = _REPO / "tests" / "fixtures" / "v43_multihead_metadata.json"
    metadata = json.loads(fixture.read_text(encoding="utf-8"))
    metadata["model_name"] = "jacksparrow_v43_BTCUSD"
    metadata["version_tag"] = "v43"
    metadata["model_family"] = V43_MULTIHEAD_MODEL_FAMILY
    metadata["artifact_format"] = V43_MULTIHEAD_ARTIFACT_FORMAT

    bundle = MultiHeadBundle()
    for hkey in V43_HORIZON_KEYS:
        fb = int(V43_HORIZON_KEY_TO_BARS[hkey])
        thr = float(
            metadata["horizons"][hkey]["validation_metrics"]["dynamic_threshold"]
        )
        bundle.set_head(fb, _stub_ensemble(threshold=thr))

    from agent.models.v43_pickle_shims import FeatureEngineer

    fe = FeatureEngineer()
    fe.columns = list(V43_CANONICAL_FEATURES)

    artifact = {
        "format": V43_MULTIHEAD_ARTIFACT_FORMAT,
        "model": bundle,
        "feature_engineer": fe,
        "features": list(V43_CANONICAL_FEATURES),
    }
    (out_dir / "metadata_v43.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    joblib.dump(artifact, out_dir / "model_artifact_v43.pkl")
    print(f"Stub bundle written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
