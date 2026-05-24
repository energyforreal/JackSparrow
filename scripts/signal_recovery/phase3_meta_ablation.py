"""Phase 3.1: A/B replay meta+calibrator vs regressor_mean on shipped v43 bundle."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from scripts.signal_recovery.kpi import compare_kpis, compute_baseline_kpis, std_or_zero

BUNDLE_DIR = Path("agent/model_storage/JackSparrow_v43_models_BTCUSD")
ARTIFACT_NAMES = (
    "model_artifact_v43_patched.pkl",
    "model_artifact_v43.pkl",
)


def _resolve_artifact() -> Path:
    for name in ARTIFACT_NAMES:
        p = BUNDLE_DIR / name
        if p.is_file():
            return p
    raise FileNotFoundError(f"v43 artifact not found under {BUNDLE_DIR}")


def _load_artifact(path: Path) -> Dict[str, Any]:
    import joblib  # type: ignore

    import agent.models.v43_pickle_shims  # noqa: F401

    art = joblib.load(path)
    if not isinstance(art, dict) or "model" not in art:
        raise ValueError("invalid v43 artifact dict")
    return art


def _synthetic_X(feats: List[str], n: int, seed: int) -> Tuple[np.ndarray, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    X = rng.normal(0.0, 1.0, size=(n, len(feats))).astype(np.float64)
    return X, pd.DataFrame(X, columns=feats)


def _predict_stack(model: Any, X: np.ndarray, X_df: pd.DataFrame, stack: str) -> np.ndarray:
    pred = getattr(model, "predict", None)
    if pred is None:
        raise RuntimeError("ensemble missing predict")
    try:
        out = pred(X, X_df=X_df, inference_stack=stack)
    except TypeError:
        setattr(model, "_inference_stack", stack)
        out = pred(X, X_df=X_df)
    return np.asarray(out, dtype=np.float64).ravel()


def run_meta_ablation(
    *,
    out_dir: Path,
    n_samples: int = 256,
    seed: int = 42,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    art_path = _resolve_artifact()
    art = _load_artifact(art_path)
    model = art["model"]
    feats = list(art.get("features") or [])
    if not feats:
        raise ValueError("artifact missing features list")

    heads: List[Dict[str, Any]] = []
    horizon_models = getattr(model, "horizon_models", None) or {}
    if not isinstance(horizon_models, dict) or not horizon_models:
        horizon_models = {int(getattr(model, "forward_bars", 6) or 6): model}

    X, X_df = _synthetic_X(feats, n_samples, seed)
    for fb, ens in sorted(horizon_models.items(), key=lambda x: int(x[0])):
        a = _predict_stack(ens, X, X_df, "meta_calibrator")
        b = _predict_stack(ens, X, X_df, "regressor_mean")
        heads.append(
            {
                "forward_bars": int(fb),
                "meta_calibrator": {
                    "std": std_or_zero(a.tolist()),
                    "min": float(np.min(a)),
                    "max": float(np.max(a)),
                    "mean": float(np.mean(a)),
                },
                "regressor_mean": {
                    "std": std_or_zero(b.tolist()),
                    "min": float(np.min(b)),
                    "max": float(np.max(b)),
                    "mean": float(np.mean(b)),
                },
                "std_delta_regressor_minus_meta": float(std_or_zero(b.tolist()) - std_or_zero(a.tolist())),
            }
        )

    pseudo_rows_a = [{"signal": "HOLD", "confidence": 0.5, "expected_return": h["meta_calibrator"]["mean"]} for h in heads]
    pseudo_rows_b = [{"signal": "HOLD", "confidence": 0.5, "expected_return": h["regressor_mean"]["mean"]} for h in heads]
    kpi_a = compute_baseline_kpis(pseudo_rows_a)
    kpi_b = compute_baseline_kpis(pseudo_rows_b)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "3.1",
        "artifact": str(art_path),
        "n_samples": n_samples,
        "per_head": heads,
        "aggregate_kpi_compare": compare_kpis(kpi_a, kpi_b),
        "recommendation_hint": (
            "If regressor_mean std materially exceeds meta_calibrator across heads, "
            "prioritize meta/calibration stack redesign before threshold tuning."
        ),
    }
    out_path = out_dir / "meta_ablation_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
