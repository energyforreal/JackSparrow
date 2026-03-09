"""
Trading Agent 2 configuration module.
Centralizes all path configurations for the project.
"""
from .paths import (
    PROJECT_ROOT,
    DATA_DIR,
    MODELS_DIR,
    XGBOOST_DIR,
    SCRIPTS_DIR,
    NOTEBOOKS_DIR,
    FEATURE_STORE_DIR,
    DATA_BACKUPS_DIR,
    DATA_DELTA_DIR,
    DATA_REDIS_DIR,
    TRAINING_SUMMARY_FILE,
    FEATURE_SCHEMA_FILE,
    TRAINING_METADATA_FILE,
    MODEL_VERSION_FILE,
    DELTA_FETCHER_SCRIPT,
    TRAIN_XGBOOST_SCRIPT,
    get_project_root,
    is_colab,
    ensure_directories,
)

__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "MODELS_DIR",
    "XGBOOST_DIR",
    "SCRIPTS_DIR",
    "NOTEBOOKS_DIR",
    "FEATURE_STORE_DIR",
    "DATA_BACKUPS_DIR",
    "DATA_DELTA_DIR",
    "DATA_REDIS_DIR",
    "TRAINING_SUMMARY_FILE",
    "FEATURE_SCHEMA_FILE",
    "TRAINING_METADATA_FILE",
    "MODEL_VERSION_FILE",
    "DELTA_FETCHER_SCRIPT",
    "TRAIN_XGBOOST_SCRIPT",
    "get_project_root",
    "is_colab",
    "ensure_directories",
]
