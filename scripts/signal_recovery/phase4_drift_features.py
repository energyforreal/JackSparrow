"""Phase 4: per-horizon drift diagnostics + microstructure feature pack stub."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from agent.learning.adaptive import drift_detector
from feature_store.drift import load_training_stats

BUNDLE_DIR = Path("agent/model_storage/JackSparrow_v43_models_BTCUSD")
META_PATH = BUNDLE_DIR / "metadata_v43.json"
_PARQUET = Path("data/labeled/BTCUSD_5m_labeled.parquet")

MICROSTRUCTURE_FEATURES = (
    "oi_delta",
    "taker_aggression_proxy",
    "liquidation_flow_proxy",
    "funding_imbalance",
)


def _load_feature_matrix() -> Optional[pd.DataFrame]:
    if not _PARQUET.is_file():
        return None
    df = pd.read_parquet(_PARQUET)
    if len(df) < 500:
        return None
    return df


def run_drift_diagnostics(*, out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = _load_feature_matrix()
    per_horizon: List[Dict[str, Any]] = []

    stats = load_training_stats(META_PATH) if META_PATH.is_file() else {}
    if df is not None:
        numeric = df.select_dtypes(include=[np.number])
        recent_n = min(2000, len(numeric) // 2)
        past_n = min(2000, len(numeric) // 2)
        recent = numeric.tail(recent_n)
        past = numeric.iloc[-(recent_n + past_n) : -recent_n]
        ks = drift_detector.detect_drift(past, recent, alpha=0.01, stat_threshold=0.10)
        psi = drift_detector.detect_drift_psi(past, recent, psi_threshold=0.20, bins=10)
        consensus = drift_detector.consensus_drift_feature_names(ks, psi)
        per_horizon.append(
            {
                "horizon_key": "all_features",
                "ks_drifted_count": len(ks),
                "psi_drifted_count": len(psi),
                "consensus_count": len(consensus),
                "top_consensus": consensus[:10],
            }
        )
        if stats:
            z_drift = []
            last = numeric.iloc[-1]
            for name, stat in list(stats.items())[:80]:
                if name not in last.index:
                    continue
                mean = float(stat.get("mean", 0.0))
                std = float(stat.get("std", 0.0))
                if std < 1e-12:
                    continue
                z = abs((float(last[name]) - mean) / std)
                if z > 4.0:
                    z_drift.append(name)
            per_horizon.append(
                {
                    "horizon_key": "training_stats_z4",
                    "drifted_feature_count": len(z_drift),
                    "sample": z_drift[:15],
                }
            )
    else:
        per_horizon.append(
            {
                "horizon_key": "skipped",
                "reason": "no labeled parquet at data/labeled/BTCUSD_5m_labeled.parquet",
            }
        )

    micro = {
        "feature_pack": list(MICROSTRUCTURE_FEATURES),
        "status": "stub_branch_experiment",
        "note": (
            "Enable in a separate training branch when consensus drift is high; "
            "not wired into production inference by default."
        ),
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": 4,
        "per_horizon_drift": per_horizon,
        "microstructure_pack": micro,
    }
    out_path = out_dir / "drift_diagnostics_report.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
