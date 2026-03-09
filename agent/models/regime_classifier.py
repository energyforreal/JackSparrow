"""
Re-export regime classifier from scripts for agent and training compatibility.
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
_scripts = _root / "scripts"
if _scripts.exists() and str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if _scripts.exists() and str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from regime_classifier import (
    REGIME_NAMES,
    REGIME_TF_WEIGHTS,
    RegimeClassifier,
    RegimeModelTrainer,
    RegimeTrainingConfig,
    compute_feature_drift_stats,
    drift_stats_to_dict,
    evaluate_sharpe_proxy,
    extract_regime_features,
    make_regime_labels,
    should_promote_model,
)

__all__ = [
    "REGIME_NAMES",
    "REGIME_TF_WEIGHTS",
    "RegimeClassifier",
    "RegimeModelTrainer",
    "RegimeTrainingConfig",
    "compute_feature_drift_stats",
    "drift_stats_to_dict",
    "evaluate_sharpe_proxy",
    "extract_regime_features",
    "make_regime_labels",
    "should_promote_model",
]
