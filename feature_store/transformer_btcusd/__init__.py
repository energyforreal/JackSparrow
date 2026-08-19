"""Per-TF BTCUSD transformer feature pipeline (train/serve parity with Colab)."""

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_NAMES,
    CONTINUOUS_LABEL_COLS,
    FEATURE_COLS,
    FEATURE_CONTRACT_VERSION,
    PATH_LABEL_HORIZON_BARS,
    REGIME_NAMES,
    RESOLUTION_MINUTES,
    SUPPORTED_RESOLUTIONS,
    TF_KEYS,
    compute_long_edge,
    compute_path_edge,
    compute_short_edge,
    default_training_config,
    path_favorable_adverse,
)
from feature_store.transformer_btcusd.features import (
    add_features,
    assemble_raw_frame,
    classify_candle_shape,
    prepare_raw_frame,
)
from feature_store.transformer_btcusd.inference import (
    build_candle_class_window,
    build_continuous_window,
    build_inference_window,
    load_feature_config,
    unstandardize_continuous,
)

__all__ = [
    "CANDLE_CLASS_NAMES",
    "CONTINUOUS_LABEL_COLS",
    "FEATURE_COLS",
    "FEATURE_CONTRACT_VERSION",
    "PATH_LABEL_HORIZON_BARS",
    "REGIME_NAMES",
    "RESOLUTION_MINUTES",
    "SUPPORTED_RESOLUTIONS",
    "TF_KEYS",
    "add_features",
    "assemble_raw_frame",
    "build_candle_class_window",
    "build_continuous_window",
    "build_inference_window",
    "classify_candle_shape",
    "compute_long_edge",
    "compute_path_edge",
    "compute_short_edge",
    "default_training_config",
    "load_feature_config",
    "path_favorable_adverse",
    "prepare_raw_frame",
    "unstandardize_continuous",
]
