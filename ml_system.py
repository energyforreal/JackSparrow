"""
Unified ML System Architecture for Trading Agent 2

Includes:
- Dynamic project paths (VS Code + Google Colab) via config.paths
- Feature Store (canonical implementation in feature_store/)
- Model Registry
- Agent model auto-update
- Feature drift monitoring
"""

import sys
from pathlib import Path

# Use shared path resolution (works in both Colab and local)
try:
    from config.paths import (
        get_project_root,
        PROJECT_ROOT,
        XGBOOST_DIR as MODEL_DIR,
        SCRIPTS_DIR,
        DATA_DIR,
        FEATURE_STORE_DIR,
        ensure_directories,
    )
except ImportError:
    # Fallback when run without package context (e.g. notebook before sys.path fix)
    PROJECT_ROOT = Path(__file__).resolve().parent
    SCRIPTS_DIR = PROJECT_ROOT / "scripts"
    MODEL_DIR = PROJECT_ROOT / "agent" / "model_storage" / "xgboost"
    DATA_DIR = PROJECT_ROOT / "data"
    FEATURE_STORE_DIR = PROJECT_ROOT / "feature_store"
    def get_project_root(override=None):
        return PROJECT_ROOT
    def ensure_directories():
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        FEATURE_STORE_DIR.mkdir(parents=True, exist_ok=True)

ensure_directories()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.append(str(SCRIPTS_DIR))

import json
import hashlib
import zipfile
import io
import pandas as pd
import numpy as np
from collections import deque
import joblib
from datetime import datetime
from typing import Any, Dict, Optional

try:
    import requests
except ImportError:
    requests = None  # optional for registry download

# ------------------------------------------------
# 2. FEATURE REGISTRY
# ------------------------------------------------

FEATURES = [
    "returns",
    "volatility",
    "atr",
    "trend",
    "volume_z",
    "adx",
    "rsi",
    "bb_width"
]

FEATURE_VERSION = "1.0"

# ------------------------------------------------
# 3. FEATURE PIPELINE
# ------------------------------------------------

def compute_features(df: pd.DataFrame):

    df = df.copy()

    df["returns"] = df["close"].pct_change()

    df["volatility"] = df["returns"].rolling(20).std()

    df["atr"] = df["high"] - df["low"]

    df["trend"] = (
        df["close"].rolling(20).mean()
        - df["close"].rolling(50).mean()
    )

    df["volume_z"] = (
        df["volume"] - df["volume"].rolling(50).mean()
    ) / df["volume"].rolling(50).std()

    # Example placeholders
    df["adx"] = df["returns"].rolling(14).std()
    df["rsi"] = df["returns"].rolling(14).mean()
    df["bb_width"] = df["volatility"] * 2

    return df[FEATURES]

# ------------------------------------------------
# 4. FEATURE CACHE (LIVE TRADING)
# ------------------------------------------------

class FeatureCache:

    def __init__(self, maxlen=500):
        self.data = deque(maxlen=maxlen)

    def update(self, candle):
        self.data.append(candle)

    def dataframe(self):
        return pd.DataFrame(self.data)

# ------------------------------------------------
# 5. FEATURE DRIFT MONITORING
# ------------------------------------------------

class FeatureDriftMonitor:

    def __init__(self, training_stats):
        self.training_stats = training_stats

    def check(self, live_features):

        for col in live_features.columns:

            train_mean = self.training_stats[col]["mean"]
            live_mean = live_features[col].mean()

            if abs(train_mean - live_mean) > 3 * self.training_stats[col]["std"]:
                print(f"WARNING: Feature drift detected for {col}")

# ------------------------------------------------
# 6. MODEL REGISTRY
# ------------------------------------------------

REGISTRY_URL = "https://raw.githubusercontent.com/YOUR_ORG/trading-model-registry/main/registry"

VERSION_FILE = MODEL_DIR / "model_version.json"
METADATA_FILE = MODEL_DIR / "metadata.json"
MODELS_ZIP = MODEL_DIR / "models.zip"

STRICT_ARTIFACTS = [
    "entry_meta.pkl", "exit_model.pkl", "regime_model.pkl",
    "entry_base.pkl", "exit_base.pkl", "entry_scaler.pkl", "exit_scaler.pkl",
    "feature_schema.json", "training_metadata.json", "training_summary.csv",
]


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_model_version_and_zip(
    model_dir: Optional[Path] = None,
    version: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Write model_version.json (with checksums), metadata.json, and models.zip.
    Call from training pipeline after strict artifacts are written.
    Returns the version doc for callers.
    """
    model_dir = model_dir or MODEL_DIR
    version = version or datetime.utcnow().strftime("%Y%m%d.%H%M%S")
    checksums: Dict[str, str] = {}
    to_zip: list = []
    for name in STRICT_ARTIFACTS:
        p = model_dir / name
        if p.exists():
            checksums[name] = _file_sha256(p)
            to_zip.append((name, p))

    version_doc = {
        "version": version,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "checksums": checksums,
        "artifacts": list(checksums.keys()),
    }

    model_dir.mkdir(parents=True, exist_ok=True)
    with open(model_dir / "model_version.json", "w") as f:
        json.dump(version_doc, f, indent=2)

    if to_zip:
        zip_path = model_dir / "models.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, p in to_zip:
                z.write(p, name)
        version_doc["models_zip_sha256"] = _file_sha256(zip_path)
        with open(model_dir / "model_version.json", "w") as f:
            json.dump(version_doc, f, indent=2)

    metadata_src = model_dir / "training_metadata.json"
    if metadata_src.exists():
        meta = json.loads(metadata_src.read_text())
        with open(model_dir / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2)
    return version_doc


def validate_model_dir(model_dir: Optional[Path] = None) -> bool:
    """Check model_version.json checksums match on-disk files. Return True if valid."""
    model_dir = model_dir or MODEL_DIR
    vf = model_dir / "model_version.json"
    if not vf.exists():
        return False
    doc = json.loads(vf.read_text())
    for name, expected in doc.get("checksums", {}).items():
        p = model_dir / name
        if not p.exists() or _file_sha256(p) != expected:
            return False
    return True


def get_latest_model() -> Dict[str, Any]:
    if not requests:
        return {}
    r = requests.get(f"{REGISTRY_URL}/latest.json")
    r.raise_for_status()
    return r.json()


def download_model(path: str) -> bytes:
    if not requests:
        raise RuntimeError("requests not installed")
    r = requests.get(f"{REGISTRY_URL}/{path}")
    r.raise_for_status()
    return r.content


def install_model(zip_bytes: bytes, model_dir: Optional[Path] = None) -> None:
    model_dir = model_dir or MODEL_DIR
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        z.extractall(model_dir)


def update_model_if_needed(model_dir: Optional[Path] = None) -> bool:
    """If a new version is available (e.g. from registry), download and install. Return True if updated."""
    model_dir = model_dir or MODEL_DIR
    if not requests:
        return False
    try:
        latest = get_latest_model()
        if not latest:
            return False
    except Exception:
        return False
    vf = model_dir / "model_version.json"
    current = {}
    if vf.exists():
        try:
            current = json.loads(vf.read_text())
        except Exception:
            pass
    if current.get("version") == latest.get("version"):
        return False
    zip_bytes = download_model(latest["path"])
    sha = hashlib.sha256(zip_bytes).hexdigest()
    if sha != latest.get("sha256"):
        raise RuntimeError("Checksum mismatch")
    install_model(zip_bytes, model_dir)
    vf.write_text(json.dumps(latest))
    return True

# ------------------------------------------------
# 7. MODEL LOADING
# ------------------------------------------------

# Optional Colab export names (when artifacts are copied flat into MODEL_DIR).
JACKSPARROW_ENTRY_ARTIFACTS = [
    "entry_long_model_BTCUSD_5m.joblib",
    "entry_short_model_BTCUSD_5m.joblib",
    "entry_long_scaler_BTCUSD_5m.joblib",
    "entry_short_scaler_BTCUSD_5m.joblib",
    "entry_long_model_BTCUSD_15m.joblib",
    "entry_short_model_BTCUSD_15m.joblib",
    "entry_long_scaler_BTCUSD_15m.joblib",
    "entry_short_scaler_BTCUSD_15m.joblib",
]


class TradingModels:
    """
    Legacy robust-ensemble loader (entry_meta.pkl / exit_model.pkl) or flat JackSparrow
    entry_long / entry_short joblibs. Production agent uses V4EnsembleNode + metadata instead.
    """

    def __init__(self):
        self.entry_model = None
        self.exit_model = None
        self._mode = "none"
        self._js_models: Dict[str, Any] = {}
        self._js_scalers: Dict[str, Any] = {}
        self.load_models()

    def load_models(self) -> None:
        print("Loading models...")
        legacy_entry = MODEL_DIR / "entry_meta.pkl"
        legacy_exit = MODEL_DIR / "exit_model.pkl"
        if legacy_entry.exists() and legacy_exit.exists():
            self._mode = "legacy"
            self.entry_model = joblib.load(legacy_entry)
            self.exit_model = joblib.load(legacy_exit)
            print("Loaded legacy entry_meta / exit_model.")
            return

        sym, tfs = "BTCUSD", ("5m", "15m")
        loaded = True
        for tf in tfs:
            for direction in ("long", "short"):
                mp = MODEL_DIR / f"entry_{direction}_model_{sym}_{tf}.joblib"
                sp = MODEL_DIR / f"entry_{direction}_scaler_{sym}_{tf}.joblib"
                if not mp.exists() or not sp.exists():
                    loaded = False
                    break
                self._js_models[f"{tf}_{direction}"] = joblib.load(mp)
                self._js_scalers[f"{tf}_{direction}"] = joblib.load(sp)
            if not loaded:
                break

        if loaded and self._js_models:
            self._mode = "jacksparrow"
            print("Loaded JackSparrow entry long/short models from MODEL_DIR.")
            return

        self._js_models.clear()
        self._js_scalers.clear()
        print(
            "WARNING: No entry_meta.pkl/exit_model.pkl and no full JackSparrow entry "
            "joblib set in MODEL_DIR. Use agent model discovery (metadata JSON) for live trading."
        )

    def predict(self, features: Any) -> tuple:
        if self._mode == "legacy" and self.entry_model is not None and self.exit_model is not None:
            entry_signal = self.entry_model.predict(features)
            exit_signal = self.exit_model.predict(features)
            return entry_signal, exit_signal

        if self._mode == "jacksparrow":
            X = np.asarray(features, dtype=np.float64).reshape(1, -1)
            # Default inference TF for this legacy helper path
            tf = "5m"
            if f"{tf}_long" not in self._js_models:
                tf = "15m"
            long_m = self._js_models.get(f"{tf}_long")
            short_m = self._js_models.get(f"{tf}_short")
            long_s = self._js_scalers.get(f"{tf}_long")
            short_s = self._js_scalers.get(f"{tf}_short")
            if long_m is None or short_m is None or long_s is None or short_s is None:
                return np.array([0.0]), np.array([0.0])
            pl = float(long_m.predict_proba(long_s.transform(X))[0, 1])
            ps = float(short_m.predict_proba(short_s.transform(X))[0, 1])
            combined = np.array([pl - ps], dtype=np.float64)
            return combined, np.array([0.0])

        return np.array([0.0]), np.array([0.0])

# ------------------------------------------------
# 8. AUTO MODEL RELOAD LOOP
# ------------------------------------------------

def start_model_update_loop(models):

    import threading
    import time

    def loop():

        while True:

            try:

                if update_model_if_needed():

                    print("Reloading models...")
                    models.load_models()

            except Exception as e:

                print("Model update failed:", e)

            time.sleep(300)

    threading.Thread(target=loop, daemon=True).start()

# ------------------------------------------------
# 9. LIVE TRADING INFERENCE PIPELINE
# ------------------------------------------------

class LiveInference:

    def __init__(self):

        self.cache = FeatureCache()
        self.models = TradingModels()

        start_model_update_loop(self.models)

    def on_new_candle(self, candle):

        self.cache.update(candle)

        df = self.cache.dataframe()

        features_df = compute_features(df)

        features = features_df.iloc[-1:].values

        entry, exit = self.models.predict(features)

        return entry, exit

# ------------------------------------------------
# 10. TRAINING UTILITIES
# ------------------------------------------------

def save_training_metadata(df):

    stats = {}

    for col in FEATURES:

        stats[col] = {
            "mean": float(df[col].mean()),
            "std": float(df[col].std())
        }

    with open(MODEL_DIR / "feature_stats.json", "w") as f:
        json.dump(stats, f, indent=2)

    metadata = {
        "feature_version": FEATURE_VERSION,
        "trained_at": datetime.utcnow().isoformat(),
        "feature_count": len(FEATURES)
    }

    with open(MODEL_DIR / "training_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

# ------------------------------------------------
# END OF SYSTEM
# ------------------------------------------------