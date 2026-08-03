"""Run per-TF transformer training from CLI or Colab."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import torch
from torch.utils.data import DataLoader

from feature_store.transformer_btcusd.contract import (
    CONTINUOUS_LABEL_COLS,
    FEATURE_COLS,
    SUPPORTED_RESOLUTIONS,
    bundle_dir_name,
    default_training_config,
)
from feature_store.transformer_btcusd.features import add_features
from feature_store.transformer_btcusd.labels import (
    compute_market_labels,
    label_nan_summary,
    trim_label_tail,
)
from scripts.colab.transformer_data import fetch_history_bundle, validate_derivatives_coverage
from scripts.colab.transformer_training import (
    MarketTransformer,
    WindowDataset,
    build_windows,
    evaluate_continuous_targets,
    evaluate_regime_accuracy,
    export_transformer_bundle,
    fit_label_stats,
    fit_vol_regime_edges,
    print_primary_metrics,
    print_target_metrics,
    set_training_seed,
    split_purged_windows,
    standardize_labels,
    to_vol_regime,
    train_transformer,
)


def run_training(
    *,
    resolution: str,
    export_dir: Path,
    epochs: int | None = None,
    history_days: int | None = None,
    raw_cache_path: Path | None = None,
    refresh_data: bool = False,
    enforce_quality_gate: bool = True,
) -> None:
    """Train and export a single per-TF transformer bundle."""
    res = resolution.strip().lower()
    if res not in SUPPORTED_RESOLUTIONS:
        raise ValueError(f"Unsupported resolution {resolution!r}; use one of {SUPPORTED_RESOLUTIONS}")

    config = dict(default_training_config(res))
    if epochs is not None:
        config["epochs"] = epochs
    if history_days is not None:
        config["history_days"] = history_days

    set_training_seed(config["seed"])
    print(json.dumps(config, indent=2))

    cache = raw_cache_path or Path(f"btcusd_{res}_raw.parquet")
    if cache.is_file() and not refresh_data:
        print(f"Loading cached raw data from {cache}")
        raw_df = pd.read_parquet(cache)
        validate_derivatives_coverage(
            raw_df,
            min_coverage=config["min_derivatives_coverage"],
            warn_coverage=config["derivatives_coverage_warn"],
        )
    else:
        raw_df = fetch_history_bundle(
            symbol=config["symbol"],
            resolution=config["resolution"],
            history_days=config["history_days"],
            base_url=config["base_url"],
            min_derivatives_coverage=config["min_derivatives_coverage"],
            derivatives_coverage_warn=config["derivatives_coverage_warn"],
        )
        cache.parent.mkdir(parents=True, exist_ok=True)
        raw_df.to_parquet(cache)
        print(f"Cached raw pull to {cache}")

    resolution_minutes = int(config["resolution_minutes"])
    feat_df = add_features(
        raw_df,
        resolution_minutes=resolution_minutes,
        atr_period=config["atr_period"],
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

    print(f"raw bars: {len(raw_df)}, feature rows: {len(feat_df)}")
    nan_rates = label_nan_summary(feat_df)
    print("label NaN rates:", nan_rates)

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

    label_mean, label_std = fit_label_stats(splits["y_train"])
    y_train_z, m_train = standardize_labels(splits["y_train"], label_mean, label_std)
    y_val_z, m_val = standardize_labels(splits["y_val"], label_mean, label_std)
    y_test_z, m_test = standardize_labels(splits["y_test"], label_mean, label_std)

    q_edges = fit_vol_regime_edges(splits["y_train"], config["vol_regime_quantiles"])
    r_train = to_vol_regime(splits["y_train"], q_edges)
    r_val = to_vol_regime(splits["y_val"], q_edges)
    r_test = to_vol_regime(splits["y_test"], q_edges)

    train_loader = DataLoader(
        WindowDataset(splits["x_train"], y_train_z, m_train, r_train),
        batch_size=config["batch_size"],
        shuffle=True,
        drop_last=True,
    )
    val_loader = DataLoader(
        WindowDataset(splits["x_val"], y_val_z, m_val, r_val),
        batch_size=config["batch_size"],
        shuffle=False,
    )
    test_loader = DataLoader(
        WindowDataset(splits["x_test"], y_test_z, m_test, r_test),
        batch_size=config["batch_size"],
        shuffle=False,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device: {device}")

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

    train_metrics = evaluate_continuous_targets(
        model,
        train_loader,
        device=device,
        label_mean=label_mean,
        label_std=label_std,
    )
    print_primary_metrics(train_metrics)
    print_target_metrics(train_metrics, title="Train set — all continuous targets:")

    test_metrics = evaluate_continuous_targets(
        model,
        test_loader,
        device=device,
        label_mean=label_mean,
        label_std=label_std,
    )
    print_primary_metrics(test_metrics)
    print_target_metrics(test_metrics, title="Test set — all continuous targets:")

    regime_accuracy = evaluate_regime_accuracy(model, test_loader, device=device)
    print(f"Regime head test accuracy: {regime_accuracy:.3f}")

    export_dir.mkdir(parents=True, exist_ok=True)
    onnx_path, cfg_path, meta_path = export_transformer_bundle(
        model,
        export_dir,
        device=device,
        window_len=config["window_len"],
        n_features=len(FEATURE_COLS),
        feature_cols=FEATURE_COLS,
        label_mean=label_mean,
        label_std=label_std,
        q_edges=q_edges,
        config=config,
        test_metrics=test_metrics,
        regime_accuracy=regime_accuracy,
        enforce_quality_gate=enforce_quality_gate,
    )
    print(f"Exported {onnx_path}")
    print(f"Exported {cfg_path}")
    print(f"Exported {meta_path}")


def run_all_training(
    *,
    resolutions: Sequence[str] | None = None,
    export_dir: Path,
    cache_dir: Path | None = None,
    epochs: int | None = None,
    history_days: int | None = None,
    refresh_data: bool = False,
    enforce_quality_gate: bool = True,
    continue_on_error: bool = False,
) -> list[dict[str, Any]]:
    """Train and export all requested per-TF transformer bundles."""
    tfs = list(resolutions or SUPPORTED_RESOLUTIONS)
    results: list[dict[str, Any]] = []
    cache_root = cache_dir or Path(".")

    for resolution in tfs:
        res = resolution.strip().lower()
        tf_export_dir = export_dir / bundle_dir_name(res)
        raw_cache_path = cache_root / f"btcusd_{res}_raw.parquet"
        print(f"\n{'=' * 60}\nTraining {res} -> {tf_export_dir}\n{'=' * 60}")

        try:
            run_training(
                resolution=res,
                export_dir=tf_export_dir,
                epochs=epochs,
                history_days=history_days,
                raw_cache_path=raw_cache_path,
                refresh_data=refresh_data,
                enforce_quality_gate=enforce_quality_gate,
            )
            results.append(
                {
                    "resolution": res,
                    "status": "ok",
                    "export_dir": str(tf_export_dir),
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "resolution": res,
                    "status": "failed",
                    "export_dir": str(tf_export_dir),
                    "error": str(exc),
                }
            )
            if not continue_on_error:
                raise

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Train per-TF BTCUSD transformer")
    parser.add_argument("--resolution", choices=list(SUPPORTED_RESOLUTIONS), default=None)
    parser.add_argument("--all", action="store_true", help="Train all supported resolutions")
    parser.add_argument("--export-dir", type=Path, default=Path("export"))
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--history-days", type=int, default=None)
    parser.add_argument("--raw-cache", type=Path, default=None)
    parser.add_argument("--refresh-data", action="store_true")
    parser.add_argument("--skip-quality-gate", action="store_true")
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="When using --all, continue training remaining TFs after a failure",
    )
    args = parser.parse_args()

    if args.all and args.resolution:
        parser.error("Use either --resolution or --all, not both")
    if not args.all and not args.resolution:
        parser.error("Specify --resolution <tf> or --all")

    enforce_quality_gate = not args.skip_quality_gate
    if args.all:
        run_all_training(
            export_dir=args.export_dir,
            epochs=args.epochs,
            history_days=args.history_days,
            refresh_data=args.refresh_data,
            enforce_quality_gate=enforce_quality_gate,
            continue_on_error=args.continue_on_error,
        )
        return

    run_training(
        resolution=args.resolution,
        export_dir=args.export_dir,
        epochs=args.epochs,
        history_days=args.history_days,
        raw_cache_path=args.raw_cache,
        refresh_data=args.refresh_data,
        enforce_quality_gate=enforce_quality_gate,
    )


def _running_under_ipython() -> bool:
    """True when executed inside Jupyter/Colab (not a plain CLI invocation)."""
    try:
        from IPython import get_ipython

        return get_ipython() is not None
    except ImportError:
        return False


if __name__ == "__main__" and not _running_under_ipython():
    main()
