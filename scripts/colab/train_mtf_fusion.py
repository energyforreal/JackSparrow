"""CLI trainer for the single multi-TF fusion bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from feature_store.transformer_btcusd.contract import (
    FUSION_BUNDLE_DIR_NAME,
    FUSION_DIRECTION_CARDINALITY,
    FUSION_EMBARGO_BARS,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_WINDOW_LEN,
    default_fusion_training_config,
)
from feature_store.transformer_btcusd.mtf_features import fusion_feature_cols
from feature_store.transformer_btcusd.mtf_frames import fusion_frames_from_fetch
from scripts.colab.mtf_fusion_model import (
    MtfFusionDataset,
    fusion_model_from_config,
    inverse_frequency_class_weights,
    train_mtf_fusion,
)
from scripts.colab.mtf_fusion_research import (
    build_dataset_from_ohlcv,
    export_fusion_bundle,
    freeze_horizon_gates,
    fusion_ready_to_promote,
    horizon_metrics,
    predict_logits,
    purged_dev_test_split,
    run_walk_forward,
    shap_grouped_stub,
)
from scripts.colab.transformer_data import fetch_history_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the v11 multi-TF fusion model")
    parser.add_argument("--export-dir", default="export/mtf_fusion")
    parser.add_argument("--history-days", type=int, default=None)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--skip-walk-forward", action="store_true")
    parser.add_argument(
        "--shap",
        action="store_true",
        help="Run Gradient SHAP on the validation split after training.",
    )
    args = parser.parse_args()

    cfg = default_fusion_training_config()
    if args.history_days is not None:
        cfg["history_days"] = int(args.history_days)
    if args.epochs is not None:
        cfg["epochs"] = int(args.epochs)
    if args.shap:
        cfg["run_shap"] = True

    print("Fetching native 5m/30m/1h/2h OHLCV (10m built from 5m)...")
    df5 = fetch_history_bundle(
        symbol="BTCUSD",
        resolution="5m",
        history_days=int(cfg["history_days"]),
        base_url=str(cfg["base_url"]),
    )
    df30 = fetch_history_bundle(
        symbol="BTCUSD",
        resolution="30m",
        history_days=int(cfg["history_days"]),
        base_url=str(cfg["base_url"]),
    )
    df1h = fetch_history_bundle(
        symbol="BTCUSD",
        resolution="1h",
        history_days=int(cfg["history_days"]),
        base_url=str(cfg["base_url"]),
    )
    df2h = fetch_history_bundle(
        symbol="BTCUSD",
        resolution="2h",
        history_days=int(cfg["history_days"]),
        base_url=str(cfg["base_url"]),
    )
    frames = fusion_frames_from_fetch(df5, df30, df1h, df2h)
    memmap_dir = Path(args.export_dir) / "fusion_windows"
    memmap_dir.mkdir(parents=True, exist_ok=True)
    windows, labels, _times = build_dataset_from_ohlcv(
        frames,
        window_len=int(cfg["window_len"]),
        stride=int(cfg.get("stride") or 4),
        memmap_dir=memmap_dir,
    )
    splits = purged_dev_test_split(
        windows,
        labels,
        train_frac=float(cfg["train_frac"]),
        val_frac=float(cfg["val_frac"]),
        embargo_bars=int(cfg.get("embargo_bars") or FUSION_EMBARGO_BARS),
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    n_features = len(fusion_feature_cols())
    wf: Dict[str, Any] = {"folds": [], "mean": {}, "std": {}}
    if not args.skip_walk_forward:
        print("Walk-forward on development span (test excluded)...")
        dev_windows = {
            res: np.concatenate(
                [splits["train"]["windows"][res], splits["val"]["windows"][res]],
                axis=0,
            )
            for res in FUSION_INPUT_RESOLUTIONS
        }
        dev_labels = np.concatenate(
            [splits["train"]["labels"], splits["val"]["labels"]], axis=0
        )
        wf = run_walk_forward(
            dev_windows, dev_labels, n_features=n_features, config=cfg, device=device
        )
        del dev_windows, dev_labels

    train_ds = MtfFusionDataset(splits["train"]["windows"], splits["train"]["labels"])
    val_ds = MtfFusionDataset(splits["val"]["windows"], splits["val"]["labels"])
    train_loader = DataLoader(train_ds, batch_size=int(cfg["batch_size"]), shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=int(cfg["batch_size"]), shuffle=False)
    class_w = torch.tensor(
        inverse_frequency_class_weights(splits["train"]["labels"], FUSION_DIRECTION_CARDINALITY),
        dtype=torch.float32,
    )
    extra = {
        "label_smoothing": float(cfg.get("label_smoothing") or 0.0),
        "horizon_weights": list(cfg.get("horizon_loss_weights") or [1.0, 0.8, 0.4]),
        "lr_schedule": str(cfg.get("lr_schedule") or "cosine"),
    }
    model = fusion_model_from_config(n_features, cfg).to(device)
    print("Training on train split; early-stop on val (test still frozen)...")
    train_mtf_fusion(
        model,
        train_loader,
        val_loader,
        device=device,
        epochs=int(cfg["epochs"]),
        lr=float(cfg["lr"]),
        weight_decay=float(cfg["weight_decay"]),
        patience=int(cfg["early_stop_patience"]),
        class_weights=class_w,
        **extra,
    )
    val_logits, val_y = predict_logits(model, val_loader, device)
    gates = freeze_horizon_gates(val_logits, val_y, wf, config=cfg)

    test_loader = DataLoader(
        MtfFusionDataset(splits["test"]["windows"], splits["test"]["labels"]),
        batch_size=int(cfg["batch_size"]),
        shuffle=False,
    )
    test_logits, test_y = predict_logits(model, test_loader, device)
    test_metrics: Dict[str, Any] = {}
    print("Final untouched test metrics:")
    for j, key in enumerate(gates["horizons"]):
        temp = float(gates["horizons"][key]["temperature"])
        m = horizon_metrics(test_logits[:, j, :], test_y[:, j], temperature=temp)
        test_metrics[key] = m
        print(
            f"  {key}: acc={m['balanced_acc']:.3f} f1={m['macro_f1']:.3f} "
            f"ece={m['ece']:.3f} pnl={m['paper_pnl']:.3f}"
        )

    promo = fusion_ready_to_promote(wf, test_metrics, gates)
    print("promotion", promo)
    if not promo["ready"]:
        print(
            "DO NOT PROMOTE: no head is MEDIUM on walk-forward mean and frozen test."
        )

    weights = model.fusion_weights().detach().cpu().numpy().tolist()
    export_dir = Path(args.export_dir) / FUSION_BUNDLE_DIR_NAME
    shap_report = shap_grouped_stub(
        fusion_feature_cols(),
        enabled=bool(cfg.get("run_shap")),
        model=model,
        val_windows=splits["val"]["windows"],
        device=device,
        config=cfg,
    )
    export_fusion_bundle(
        model,
        export_dir,
        n_features=n_features,
        window_len=int(cfg["window_len"]),
        config=cfg,
        gates=gates,
        fusion_weights=weights,
        test_metrics=test_metrics,
    )
    (export_dir / "shap_report.json").write_text(
        json.dumps(shap_report, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Exported {export_dir}")


if __name__ == "__main__":
    main()
