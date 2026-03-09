"""
Central path configuration for Trading Agent 2 project.
Eliminates hardcoded paths and Google Drive dependencies.
Supports both VS Code local and Google Colab runtimes via dynamic root detection.
"""
import os
import sys
from pathlib import Path
from typing import Optional

# Markers that identify project root (any one is sufficient)
_ROOT_MARKERS = ("agent", "scripts", ".git", "pyproject.toml", "docker-compose.yml")


def is_colab() -> bool:
    """True if running inside Google Colab."""
    if os.environ.get("COLAB_GPU"):
        return True
    try:
        import google.colab  # noqa: F401
        return True
    except ImportError:
        return False


def get_project_root(override: Optional[Path] = None) -> Path:
    """
    Resolve project root for both local and Colab. Use this everywhere instead of
    hardcoded paths. Order: env override -> explicit override -> upward marker search -> __file__ fallback -> cwd.
    """
    if override is not None and override.is_dir():
        return override.resolve()
    env_root = os.environ.get("TRADING_AGENT_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.is_dir():
            return p
    cwd = Path.cwd()
    # Search upward from cwd (works when notebook/script is run from repo or /content)
    current = cwd
    for _ in range(10):
        if current == current.parent:
            break
        for marker in _ROOT_MARKERS:
            target = current / marker
            if marker in ("agent", "scripts") and target.is_dir():
                return current
            if marker in (".git", "pyproject.toml", "docker-compose.yml") and target.exists():
                return current
        current = current.parent
    # Fallback: __file__ (this file is config/paths.py, so parent.parent = project root)
    try:
        this_file = Path(__file__).resolve()
        root = this_file.parent.parent
        if (root / "agent").is_dir() or (root / "scripts").is_dir():
            return root
    except Exception:
        pass
    return cwd


PROJECT_ROOT = get_project_root()

# Core directories
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "agent" / "model_storage"
XGBOOST_DIR = MODELS_DIR / "xgboost"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
NOTEBOOKS_DIR = PROJECT_ROOT / "notebooks"
FEATURE_STORE_DIR = PROJECT_ROOT / "feature_store"

# Data subdirectories
DATA_BACKUPS_DIR = DATA_DIR / "backups"
DATA_DELTA_DIR = DATA_BACKUPS_DIR / "delta"
DATA_REDIS_DIR = DATA_DIR / "redis"

# Model files (strict artifact contract)
TRAINING_SUMMARY_FILE = XGBOOST_DIR / "training_summary.csv"
FEATURE_SCHEMA_FILE = XGBOOST_DIR / "feature_schema.json"
TRAINING_METADATA_FILE = XGBOOST_DIR / "training_metadata.json"
MODEL_VERSION_FILE = XGBOOST_DIR / "model_version.json"

# Fetcher script
DELTA_FETCHER_SCRIPT = SCRIPTS_DIR / "delta_historical_fetcher.py"
TRAIN_XGBOOST_SCRIPT = SCRIPTS_DIR / "train_xgboost_colab.py"


def ensure_directories() -> None:
    """Create essential directories if they don't exist. Call explicitly; no import-side effects."""
    for directory in [XGBOOST_DIR, DATA_BACKUPS_DIR, DATA_DELTA_DIR, FEATURE_STORE_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    ensure_directories()
    print("Trading Agent 2 — Path Configuration")
    print("=" * 70)
    print(f"PROJECT_ROOT:         {PROJECT_ROOT}")
    print(f"is_colab():           {is_colab()}")
    print(f"DATA_DIR:             {DATA_DIR}")
    print(f"MODELS_DIR:           {MODELS_DIR}")
    print(f"XGBOOST_DIR:          {XGBOOST_DIR}")
    print(f"SCRIPTS_DIR:          {SCRIPTS_DIR}")
    print(f"NOTEBOOKS_DIR:        {NOTEBOOKS_DIR}")
    print(f"\nDATA_BACKUPS_DIR:     {DATA_BACKUPS_DIR}")
    print(f"DATA_DELTA_DIR:       {DATA_DELTA_DIR}")
    print(f"\nTRAINING_SUMMARY_FILE: {TRAINING_SUMMARY_FILE}")
    print(f"FEATURE_SCHEMA_FILE:   {FEATURE_SCHEMA_FILE}")
    print(f"\nDELTA_FETCHER_SCRIPT:  {DELTA_FETCHER_SCRIPT}")
    print(f"TRAIN_XGBOOST_SCRIPT:  {TRAIN_XGBOOST_SCRIPT}")
    print("=" * 70)
