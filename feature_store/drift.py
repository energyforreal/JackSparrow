"""
Live feature drift monitoring against training baseline.

Load training_stats from feature_schema.json (or training_metadata.json)
and check live feature vectors for drift beyond a sigma threshold.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Union


def load_training_stats(path: Union[str, Path]) -> Dict[str, Dict[str, float]]:
    """
    Load training feature statistics (mean/std) from feature_schema.json
    or training_metadata.json. Returns dict mapping feature name -> {mean, std}.
    """
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    stats = data.get("training_stats") or data.get("feature_drift_stats")
    if isinstance(stats, dict) and stats:
        return stats
    # feature_drift_{tag}.json has "features" key
    if "features" in data and isinstance(data["features"], dict):
        return data["features"]
    return {}


def check_drift(
    feature_vector: List[float],
    feature_names: List[str],
    training_stats: Dict[str, Dict[str, float]],
    threshold_sigma: float = 4.0,
) -> List[str]:
    """
    Return names of features that exceed the drift threshold (live value vs
    training mean in units of training std).
    """
    drifted: List[str] = []
    for name, val in zip(feature_names, feature_vector):
        stat = training_stats.get(name)
        if stat is None:
            continue
        mean = stat.get("mean", 0.0)
        std = stat.get("std", 0.0)
        if std < 1e-12:
            continue
        z = abs((float(val) - mean) / std)
        if z > threshold_sigma:
            drifted.append(name)
    return drifted


def drift_checker_from_schema(
    schema_path: Union[str, Path],
    feature_names: Optional[List[str]] = None,
    threshold_sigma: float = 4.0,
):
    """
    Return a callable (feature_vector) -> List[str] that checks drift using
    stats loaded from schema_path. If feature_names is None, use the
    feature list from the schema.
    """
    stats = load_training_stats(schema_path)
    if not stats:
        return lambda _: []
    names = feature_names or list(stats.keys())
    return lambda vec: check_drift(vec, names, stats, threshold_sigma)


# Pattern feature prefixes for activation rate monitoring
PATTERN_FEATURE_PREFIXES = ("cdl_", "chp_", "sr_", "tl_", "bo_")


def get_pattern_feature_activation_rates(
    feature_vectors: List[List[float]],
    feature_names: List[str],
) -> Dict[str, float]:
    """
    Compute activation rate (fraction of 1s) for binary pattern features
    across a batch of feature vectors. Used to track live distribution
    vs training baseline.
    """
    if not feature_vectors:
        return {}
    n = len(feature_vectors)
    sums: Dict[str, float] = {}
    for vec in feature_vectors:
        for name, val in zip(feature_names, vec):
            if any(name.startswith(p) for p in PATTERN_FEATURE_PREFIXES):
                sums[name] = sums.get(name, 0) + (1.0 if float(val) > 0.5 else 0.0)
    return {k: v / n for k, v in sums.items()}


def check_pattern_activation_drift(
    live_rates: Dict[str, float],
    training_rates: Dict[str, float],
    threshold: float = 0.15,
) -> List[str]:
    """
    Return pattern features whose live activation rate diverges from training
    by more than threshold (absolute difference).
    """
    drifted = []
    for name, live_val in live_rates.items():
        train_val = training_rates.get(name)
        if train_val is None:
            continue
        if abs(live_val - train_val) > threshold:
            drifted.append(name)
    return drifted
