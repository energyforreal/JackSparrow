"""Adaptive drift detection and warm-start retraining (legacy pipeline bundles only)."""

from agent.learning.adaptive.adaptive_controller import (
    hot_reload_models,
    maybe_retrain_timeframe,
    run_adaptive_retrain_tick,
)
from agent.learning.adaptive.drift_detector import (
    detect_drift,
    detect_drift_psi,
    should_retrain_from_drift,
    should_retrain_from_psi,
)
from agent.learning.adaptive.labeled_data import load_labeled_parquet
from agent.learning.adaptive.model_registry import (
    find_metadata_path,
    load_pipeline_bundle,
    rollback_active_pipeline,
    save_accepted_adaptive_pipeline,
)
from agent.learning.adaptive.model_validator import (
    macro_f1,
    validate_f1_improvement,
    validate_model_upgrade,
)
from agent.learning.adaptive.retrain_engine import (
    class_weights_to_sample_weight,
    prepare_training_matrix,
    warm_start_retrain,
)

__all__ = [
    "class_weights_to_sample_weight",
    "detect_drift",
    "detect_drift_psi",
    "find_metadata_path",
    "hot_reload_models",
    "load_labeled_parquet",
    "load_pipeline_bundle",
    "macro_f1",
    "maybe_retrain_timeframe",
    "prepare_training_matrix",
    "rollback_active_pipeline",
    "run_adaptive_retrain_tick",
    "save_accepted_adaptive_pipeline",
    "should_retrain_from_drift",
    "should_retrain_from_psi",
    "validate_f1_improvement",
    "validate_model_upgrade",
    "warm_start_retrain",
]
