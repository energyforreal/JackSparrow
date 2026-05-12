"""Verify v43 pickle shims enable joblib.load and predict on the shipped bundle.

These tests are skipped when the v43 bundle is not present in the workspace
(e.g. CI without the binary artifact).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BUNDLE_DIR = Path("agent/model_storage/JackSparrow_v43_models_BTCUSD")
ARTIFACT = BUNDLE_DIR / "model_artifact_v43.pkl"


pytestmark = pytest.mark.skipif(
    not ARTIFACT.is_file(), reason="v43 model bundle not present"
)


def test_shim_install_aliases_main():
    """Importing the shim module aliases its classes onto __main__."""
    import sys

    from agent.models import v43_pickle_shims

    main_mod = sys.modules.get("__main__")
    assert main_mod is not None
    for cls in (
        v43_pickle_shims.EnsembleModel,
        v43_pickle_shims.LGBMModel,
        v43_pickle_shims.FeatureEngineer,
    ):
        alias = getattr(main_mod, cls.__name__, None)
        assert alias is cls, f"__main__.{cls.__name__} not aliased to shim"


def test_v43_artifact_loads_via_joblib():
    """joblib.load no longer raises AttributeError for __main__.EnsembleModel."""
    import joblib  # type: ignore

    import agent.models.v43_pickle_shims  # noqa: F401  install __main__ aliases

    art = joblib.load(ARTIFACT)
    assert isinstance(art, dict)
    assert "model" in art and "feature_engineer" in art
    model = art["model"]
    assert hasattr(model, "predict")
    fe = art["feature_engineer"]
    assert hasattr(fe, "transform")


def test_v43_ensemble_predict_returns_finite_array():
    """Synthetic 40-feature input yields a finite expected_return prediction."""
    import joblib  # type: ignore

    import agent.models.v43_pickle_shims  # noqa: F401

    art = joblib.load(ARTIFACT)
    model = art["model"]
    feats = list(art.get("features") or [])
    assert len(feats) == 40
    rng = np.random.default_rng(0)
    X = rng.normal(0.0, 1.0, size=(2, len(feats))).astype(np.float64)
    X_df = pd.DataFrame(X, columns=feats)
    out = model.predict(X, X_df=X_df)
    arr = np.asarray(out, dtype=np.float64)
    assert arr.shape == (2,)
    assert np.all(np.isfinite(arr)), f"predict produced non-finite values: {arr}"


def test_v43_feature_engineer_without_pipeline_raises_clear_error():
    """The shipped feature_engineer.pkl has only ``columns``; transform must
    fail with a clear error pointing the user to either cloudpickle re-export
    or a registered build_feature_matrix function."""
    import joblib  # type: ignore

    import agent.models.v43_pickle_shims as shims

    # Ensure no test-leftover ``build_feature_matrix`` is registered.
    shims.set_v43_build_feature_matrix(None)

    art = joblib.load(ARTIFACT)
    fe = art["feature_engineer"]
    df_5m = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=10, freq="5min", tz="UTC"),
            "open": np.arange(10),
            "high": np.arange(10) + 1,
            "low": np.arange(10) - 1,
            "close": np.arange(10) + 0.5,
            "volume": np.ones(10),
        }
    )
    with pytest.raises(RuntimeError, match=r"(build_feature_matrix|cloudpickle)"):
        fe.transform(df_5m, df_5m, df_5m, df_5m, include_target=False)


def test_v43_feature_engineer_uses_registered_pipeline():
    """When set_v43_build_feature_matrix injects a function, transform delegates."""
    import joblib  # type: ignore

    import agent.models.v43_pickle_shims as shims

    art = joblib.load(ARTIFACT)
    fe = art["feature_engineer"]
    cols = list(getattr(fe, "columns") or [])

    def fake_bfm(df5, df15, df1h, df_funding, *, for_training: bool):
        n = len(df5)
        out = pd.DataFrame({c: np.zeros(n) for c in cols})
        out["timestamp"] = df5["timestamp"].values
        return out

    shims.set_v43_build_feature_matrix(fake_bfm)
    try:
        df_5m = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=4, freq="5min", tz="UTC"),
                "open": np.arange(4),
                "high": np.arange(4) + 1,
                "low": np.arange(4) - 1,
                "close": np.arange(4) + 0.5,
                "volume": np.ones(4),
            }
        )
        out = fe.transform(df_5m, df_5m, df_5m, df_5m, include_target=False)
        assert isinstance(out, pd.DataFrame)
        for c in cols:
            assert c in out.columns
    finally:
        shims.set_v43_build_feature_matrix(None)
