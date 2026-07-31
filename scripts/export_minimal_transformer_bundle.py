"""Export a minimal transformer bundle for local dev/testing.

Trains a tiny model on synthetic data (1 epoch) and writes ONNX + feature_config
into agent/model_storage/JackSparrow_Transformer_BTCUSD/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feature_store.transformer_btcusd_15m.contract import (
    CONTINUOUS_LABEL_COLS,
    DEFAULT_TRAINING_CONFIG,
    FEATURE_COLS,
)
from feature_store.transformer_btcusd_15m.features import add_features
from feature_store.transformer_btcusd_15m.labels import compute_market_labels, trim_label_tail
from scripts.colab.transformer_training import (
    MarketTransformer,
    WindowDataset,
    build_windows,
    export_transformer_bundle,
    fit_label_stats,
    fit_vol_regime_edges,
    set_training_seed,
    split_purged_windows,
    standardize_labels,
    to_vol_regime,
    train_transformer,
)

BUNDLE_DIR = ROOT / "agent" / "model_storage" / "JackSparrow_Transformer_BTCUSD"


def _synthetic_ohlcv(n_bars: int = 2500, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n_bars, freq="15min", tz="UTC")
    log_ret = rng.normal(0.0, 0.001, size=n_bars)
    close = 50000.0 * np.exp(np.cumsum(log_ret))
    high = close * (1.0 + rng.uniform(0.0001, 0.002, size=n_bars))
    low = close * (1.0 - rng.uniform(0.0001, 0.002, size=n_bars))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = rng.uniform(10.0, 100.0, size=n_bars)
    return pd.DataFrame(
        {
            "time": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def main() -> None:
    config = dict(DEFAULT_TRAINING_CONFIG)
    config["epochs"] = 1
    config["batch_size"] = 32
    set_training_seed(config["seed"])

    raw_df = _synthetic_ohlcv(n_bars=2500)
    raw_df["funding_rate"] = 0.0001
    raw_df["open_interest"] = 1e6
    feat_df = add_features(raw_df, atr_period=config["atr_period"]).dropna().reset_index(drop=True)
    feat_df = compute_market_labels(
        feat_df,
        return_horizon_bars=config["return_horizon_bars"],
        path_label_horizon_bars=config["path_label_horizon_bars"],
        mae_floor_atr_mult=config["mae_floor_atr_mult"],
    )
    feat_df = trim_label_tail(
        feat_df,
        return_horizon_bars=config["return_horizon_bars"],
        path_label_horizon_bars=config["path_label_horizon_bars"],
    )

    x_all, y_all = build_windows(
        feat_df,
        FEATURE_COLS,
        CONTINUOUS_LABEL_COLS,
        config["window_len"],
        config["stride"],
    )
    splits = split_purged_windows(
        x_all,
        y_all,
        train_frac=config["train_frac"],
        val_frac=config["val_frac"],
        embargo_bars=config["embargo_bars"],
    )
    x_train, y_train = splits["x_train"], splits["y_train"]
    x_val, y_val = splits["x_val"], splits["y_val"]

    label_mean, label_std = fit_label_stats(y_train)
    y_train_z, m_train = standardize_labels(y_train, label_mean, label_std)
    y_val_z, m_val = standardize_labels(y_val, label_mean, label_std)
    q_edges = fit_vol_regime_edges(y_train, config["vol_regime_quantiles"])
    r_train = to_vol_regime(y_train, q_edges)
    r_val = to_vol_regime(y_val, q_edges)

    train_loader = DataLoader(
        WindowDataset(x_train, y_train_z, m_train, r_train),
        batch_size=config["batch_size"],
        shuffle=True,
        drop_last=True,
    )
    val_loader = DataLoader(
        WindowDataset(x_val, y_val_z, m_val, r_val),
        batch_size=config["batch_size"],
        shuffle=False,
    )

    device = torch.device("cpu")
    model = MarketTransformer(
        n_features=len(FEATURE_COLS),
        d_model=config["d_model"],
        nhead=config["nhead"],
        num_layers=config["num_layers"],
        dropout=config["dropout"],
        max_len=config["window_len"],
        n_continuous=len(CONTINUOUS_LABEL_COLS),
    ).to(device)

    result = train_transformer(model, train_loader, val_loader, config, device=device)
    model.load_state_dict(result.model_state)
    model.eval()

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    onnx_path, cfg_path = export_transformer_bundle(
        model,
        BUNDLE_DIR,
        device=device,
        window_len=config["window_len"],
        n_features=len(FEATURE_COLS),
        feature_cols=FEATURE_COLS,
        label_mean=label_mean,
        label_std=label_std,
        q_edges=q_edges,
        config=config,
        verify=True,
    )
    meta_path = BUNDLE_DIR / "metadata_transformer.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"Missing bundle manifest: {meta_path}")
    print(json.dumps({"onnx": str(onnx_path), "feature_config": str(cfg_path)}, indent=2))


if __name__ == "__main__":
    main()
