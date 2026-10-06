"""CLI trainer for the single multi-TF fusion bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd
import numpy as np
import torch

from feature_store.transformer_btcusd.contract import (
    FUSION_V15_BUNDLE_DIR_NAME,
    LABEL_V2_DIRECTION_CARDINALITY,
    FUSION_EMBARGO_BARS,
    default_fusion_training_config,
    fusion_feature_cols_v14,
)
from feature_store.transformer_btcusd.mtf_frames import fusion_frames_from_fetch
from scripts.colab.mtf_fusion_model import (
    fusion_class_weight_tensor,
    fusion_model_from_config,
    tensor_to_numpy,
    train_mtf_fusion,
)
from scripts.colab.mtf_fusion_research import (
    _fusion_train_extra,
    build_dataset_from_ohlcv,
    development_prefix,
    export_fusion_bundle,
    freeze_horizon_gates,
    fusion_ready_to_promote,
    horizon_metrics,
    loader_runtime_kwargs,
    make_loader,
    optuna_search,
    predict_logits,
    purged_dev_test_split,
    run_leave_one_group_out,
    run_walk_forward,
    shap_grouped_stub,
    slice_id_windows,
)
from scripts.colab.transformer_data import fetch_history_bundle


def _load_or_fetch_ohlcv(
    resolution: str,
    *,
    history_days: int,
    base_url: str,
    parquet_dir: Optional[Path],
) -> pd.DataFrame:
    """Reuse cached native OHLCV when present; otherwise fetch and cache."""
    if parquet_dir is not None:
        path = parquet_dir / f"btcusd_{resolution}_raw.parquet"
        if path.is_file():
            df = pd.read_parquet(path)
            print(f"Loaded cache {path} rows={len(df)}")
            return df
    print(f"Fetching BTCUSD {resolution} OHLCV for {history_days}d...")
    df = fetch_history_bundle(
        symbol="BTCUSD",
        resolution=resolution,
        history_days=int(history_days),
        base_url=str(base_url),
    )
    if parquet_dir is not None:
        parquet_dir.mkdir(parents=True, exist_ok=True)
        out = parquet_dir / f"btcusd_{resolution}_raw.parquet"
        df.to_parquet(out, index=False)
        print(f"Wrote cache {out}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train the v15 Label V2 multi-TF fusion research model"
    )
    parser.add_argument("--export-dir", default="export/mtf_fusion_v15")
    parser.add_argument("--history-days", type=int, default=None)
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--skip-walk-forward", action="store_true")
    parser.add_argument(
        "--shap",
        action="store_true",
        help="Run Gradient SHAP on the validation split after training.",
    )
    parser.add_argument(
        "--optuna-refresh",
        action="store_true",
        help="Ignore cached optuna_best.json and run a new search.",
    )
    parser.add_argument(
        "--leave-one-group-out",
        action="store_true",
        help="Train leave-one-group-out knockouts after the main run.",
    )
    parser.add_argument(
        "--parquet-dir",
        default="export/fusion_diagnostics",
        help="Load/cache native OHLCV as btcusd_{tf}_raw.parquet.",
    )
    args = parser.parse_args()

    cfg = default_fusion_training_config()
    if args.history_days is not None:
        cfg["history_days"] = int(args.history_days)
    if args.epochs is not None:
        cfg["epochs"] = int(args.epochs)
    if args.shap:
        cfg["run_shap"] = True
    if args.optuna_refresh:
        cfg["optuna_refresh"] = True
        cfg["run_optuna"] = True
    if args.leave_one_group_out:
        cfg["run_leave_one_group_out"] = True

    parquet_dir = Path(args.parquet_dir) if str(args.parquet_dir).strip() else None
    print(
        "experiment",
        cfg.get("experiment"),
        "use_class_weights",
        cfg.get("use_class_weights"),
    )
    print("path_loss_weights", cfg.get("path_loss_weights"))
    print("Loading native 5m/30m/1h/2h OHLCV (10m built from 5m)...")
    fetch_kw = {
        "history_days": int(cfg["history_days"]),
        "base_url": str(cfg["base_url"]),
        "parquet_dir": parquet_dir,
    }
    df5 = _load_or_fetch_ohlcv("5m", **fetch_kw)
    df30 = _load_or_fetch_ohlcv("30m", **fetch_kw)
    df1h = _load_or_fetch_ohlcv("1h", **fetch_kw)
    df2h = _load_or_fetch_ohlcv("2h", **fetch_kw)
    frames = fusion_frames_from_fetch(df5, df30, df1h, df2h)
    memmap_dir = Path(args.export_dir) / "fusion_windows"
    memmap_dir.mkdir(parents=True, exist_ok=True)
    built = build_dataset_from_ohlcv(
        frames,
        window_lens=cfg.get("window_lens"),
        window_len=int(cfg["window_len"]),
        stride=int(cfg.get("stride") or 4),
        memmap_dir=memmap_dir,
    )
    windows, labels, _times = built.windows, built.labels, built.decision_times
    candle_ids, chart_ids = built.candle_ids, built.chart_ids
    splits = purged_dev_test_split(
        windows,
        labels,
        train_frac=float(cfg["train_frac"]),
        val_frac=float(cfg["val_frac"]),
        embargo_bars=int(cfg.get("embargo_bars") or FUSION_EMBARGO_BARS),
        candle_ids=candle_ids,
        chart_ids=chart_ids,
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    n_features = len(fusion_feature_cols_v14())
    loader_kw = loader_runtime_kwargs(cfg, device)
    train_loader = make_loader(
        splits["train"]["windows"],
        splits["train"]["labels"],
        batch_size=int(cfg["batch_size"]),
        shuffle=True,
        candle_ids=splits["train"].get("candle_ids"),
        chart_ids=splits["train"].get("chart_ids"),
        **loader_kw,
    )
    val_loader = make_loader(
        splits["val"]["windows"],
        splits["val"]["labels"],
        batch_size=int(cfg["batch_size"]),
        shuffle=False,
        candle_ids=splits["val"].get("candle_ids"),
        chart_ids=splits["val"].get("chart_ids"),
        **loader_kw,
    )
    class_w = fusion_class_weight_tensor(
        splits["train"]["labels"], LABEL_V2_DIRECTION_CARDINALITY, cfg
    )
    if class_w is None:
        print("class weights: off (uniform CE)")
    else:
        print("class weights", np.round(tensor_to_numpy(class_w), 3).tolist())
    cache_root = Path(args.export_dir)
    if cfg.get("run_optuna"):
        cfg = optuna_search(
            cfg,
            n_features=n_features,
            train_loader=train_loader,
            val_loader=val_loader,
            device=device,
            class_weights=class_w,
            cache_dir=cache_root,
        )
    wf: Dict[str, Any] = {"folds": [], "mean": {}, "std": {}}
    if not args.skip_walk_forward:
        print("Walk-forward on contiguous prefix through val (test excluded)...")
        dev_windows, dev_labels = development_prefix(
            windows,
            labels,
            train_frac=float(cfg["train_frac"]),
            val_frac=float(cfg["val_frac"]),
        )
        wf = run_walk_forward(
            dev_windows,
            dev_labels,
            n_features=n_features,
            config=cfg,
            device=device,
            candle_ids=slice_id_windows(candle_ids, slice(0, len(dev_labels))),
            chart_ids=slice_id_windows(chart_ids, slice(0, len(dev_labels))),
        )
        del dev_windows, dev_labels

    extra = _fusion_train_extra(cfg)
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
    ckpt_path = Path(args.export_dir) / "best.pt"
    torch.save({"state_dict": model.state_dict(), "config": dict(cfg)}, ckpt_path)
    print(f"Wrote checkpoint {ckpt_path}")
    val_logits, val_y = predict_logits(model, val_loader, device)
    gates = freeze_horizon_gates(val_logits, val_y, wf, config=cfg)

    test_loader = make_loader(
        splits["test"]["windows"],
        splits["test"]["labels"],
        batch_size=int(cfg["batch_size"]),
        shuffle=False,
        candle_ids=splits["test"].get("candle_ids"),
        chart_ids=splits["test"].get("chart_ids"),
        **loader_kw,
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
            "DO NOT PROMOTE: v15 Label V2 research export is not live-compatible "
            f"({promo.get('reason')})."
        )

    weights = tensor_to_numpy(model.fusion_weights()).tolist()
    export_dir = Path(args.export_dir) / FUSION_V15_BUNDLE_DIR_NAME
    shap_report = shap_grouped_stub(
        fusion_feature_cols_v14(),
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
        window_lens=cfg.get("window_lens"),
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
    if cfg.get("run_leave_one_group_out"):
        print("Leave-one-group-out (val split, same training budget)...")
        logo = run_leave_one_group_out(
            windows,
            labels,
            n_features=n_features,
            config=cfg,
            device=device,
            candle_ids=candle_ids,
            chart_ids=chart_ids,
        )
        (export_dir / "leave_one_group_out.json").write_text(
            json.dumps(logo, indent=2, default=str),
            encoding="utf-8",
        )
    print(f"Exported {export_dir}")


if __name__ == "__main__":
    main()
