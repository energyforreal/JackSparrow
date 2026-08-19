"""Export a minimal transformer bundle for local dev/testing.

Trains a tiny model on synthetic data (1 epoch) and writes ONNX + feature_config
into agent/model_storage/JackSparrow_Transformer_BTCUSD_15m/.
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

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_CARDINALITY,
    CONTINUOUS_LABEL_COLS,
    FUTURE_CANDLE_COL,
    STRUCTURE_OUTCOME_COL,
    bundle_dir_name,
    default_training_config,
    feature_cols_for_resolution,
)
from feature_store.transformer_btcusd.features import add_features
from feature_store.transformer_btcusd.labels import compute_market_labels, trim_label_tail
from scripts.colab.transformer_training import (
    MarketTransformer,
    WindowDataset,
    build_class_targets,
    build_windows,
    export_transformer_bundle,
    fit_label_stats,
    fit_vol_regime_edges,
    inverse_frequency_class_weights,
    set_training_seed,
    split_purged_windows,
    standardize_labels,
    to_vol_regime,
    train_transformer,
)

RESOLUTION = "15m"
BUNDLE_DIR = ROOT / "agent" / "model_storage" / bundle_dir_name(RESOLUTION)


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
    config = dict(default_training_config(RESOLUTION))
    config["epochs"] = 1
    config["batch_size"] = 32
    set_training_seed(config["seed"])

    raw_df = _synthetic_ohlcv(n_bars=2500)
    raw_df["funding_rate"] = 0.0001
    raw_df["open_interest"] = 1e6
    feature_cols = feature_cols_for_resolution(RESOLUTION)
    feat_df = add_features(
        raw_df,
        atr_period=config["atr_period"],
        resolution_minutes=config["resolution_minutes"],
    ).dropna().reset_index(drop=True)
    feat_df = compute_market_labels(
        feat_df,
        path_label_horizon_bars=config["path_label_horizon_bars"],
        mae_floor_atr_mult=config["mae_floor_atr_mult"],
    )
    feat_df = trim_label_tail(
        feat_df,
        path_label_horizon_bars=config["path_label_horizon_bars"],
    )

    x_all, x_cat_all, y_all = build_windows(
        feat_df,
        feature_cols,
        CONTINUOUS_LABEL_COLS,
        config["window_len"],
        config["stride"],
    )
    struct_all = build_class_targets(
        feat_df, STRUCTURE_OUTCOME_COL, config["window_len"], config["stride"]
    )
    candle_all = build_class_targets(
        feat_df, FUTURE_CANDLE_COL, config["window_len"], config["stride"]
    )
    splits = split_purged_windows(
        {
            "x": x_all,
            "x_cat": x_cat_all,
            "y": y_all,
            "structure": struct_all,
            "candle": candle_all,
        },
        train_frac=config["train_frac"],
        val_frac=config["val_frac"],
        embargo_bars=config["embargo_bars"],
    )
    x_train, x_cat_train, y_train = (
        splits["train"]["x"],
        splits["train"]["x_cat"],
        splits["train"]["y"],
    )
    x_val, x_cat_val, y_val = (
        splits["val"]["x"],
        splits["val"]["x_cat"],
        splits["val"]["y"],
    )

    label_mean, label_std = fit_label_stats(y_train)
    y_train_z, m_train = standardize_labels(y_train, label_mean, label_std)
    y_val_z, m_val = standardize_labels(y_val, label_mean, label_std)
    q_edges = fit_vol_regime_edges(y_train, config["vol_regime_quantiles"])
    r_train = to_vol_regime(y_train, q_edges)
    r_val = to_vol_regime(y_val, q_edges)
    candle_weights = inverse_frequency_class_weights(
        splits["train"]["candle"], CANDLE_CLASS_CARDINALITY
    )

    train_loader = DataLoader(
        WindowDataset(
            x_train,
            x_cat_train,
            y_train_z,
            m_train,
            r_train,
            splits["train"]["structure"],
            splits["train"]["candle"],
        ),
        batch_size=config["batch_size"],
        shuffle=True,
        drop_last=True,
    )
    val_loader = DataLoader(
        WindowDataset(
            x_val,
            x_cat_val,
            y_val_z,
            m_val,
            r_val,
            splits["val"]["structure"],
            splits["val"]["candle"],
        ),
        batch_size=config["batch_size"],
        shuffle=False,
    )

    device = torch.device("cpu")
    model = MarketTransformer(
        n_features=len(feature_cols),
        d_model=config["d_model"],
        nhead=config["nhead"],
        num_layers=config["num_layers"],
        dropout=config["dropout"],
        max_len=config["window_len"],
        n_continuous=len(CONTINUOUS_LABEL_COLS),
    ).to(device)

    result = train_transformer(
        model,
        train_loader,
        val_loader,
        config,
        device=device,
        candle_class_weights=candle_weights,
    )
    model.load_state_dict(result.model_state)
    model.eval()

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    onnx_path, cfg_path, _meta_path = export_transformer_bundle(
        model,
        BUNDLE_DIR,
        device=device,
        window_len=config["window_len"],
        n_features=len(feature_cols),
        feature_cols=feature_cols,
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
