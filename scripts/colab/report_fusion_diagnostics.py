"""CLI: v15 fusion diagnostics. Does not train or export a Transformer."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from feature_store.transformer_btcusd.contract import (
    default_fusion_training_config,
    fusion_feature_cols_v14,
)
from feature_store.transformer_btcusd.mtf_frames import fusion_frames_from_fetch
from scripts.colab.fusion_diagnostics import purged_index_slices, run_fusion_diagnostics
from scripts.colab.transformer_data import fetch_candles, validate_ohlcv_completeness


def _load_parquet_or_fetch(
    parquet: Optional[Path],
    *,
    history_days: int,
    base_url: str,
    cache_path: Path,
    resolution: str = "5m",
) -> pd.DataFrame:
    if parquet is not None:
        path = Path(parquet)
        if not path.is_file():
            raise FileNotFoundError(f"parquet not found: {path}")
        df = pd.read_parquet(path)
        print(f"Loaded {path} rows={len(df)}")
        return df
    if cache_path.is_file():
        df = pd.read_parquet(cache_path)
        print(f"Loaded cache {cache_path} rows={len(df)}")
        return df
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=int(history_days))
    print(f"Fetching BTCUSD {resolution} OHLCV for {history_days}d...")
    raw = fetch_candles(
        "BTCUSD",
        resolution,
        int(start_dt.timestamp()),
        int(end_dt.timestamp()),
        base_url,
    )
    report = validate_ohlcv_completeness(raw, resolution, symbol="BTCUSD")
    print(
        f"OHLCV BTCUSD {resolution}: {report['rows']} bars, "
        f"completeness {report['completeness']:.1%}, gaps={report['gaps']}"
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    raw.to_parquet(cache_path, index=False)
    print(f"Wrote cache {cache_path}")
    return raw


def _load_htf_frames(cache_dir: Path, df5m: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    native = {}
    for res in ("30m", "1h", "2h"):
        path = cache_dir / f"btcusd_{res}_raw.parquet"
        if path.is_file():
            native[res] = pd.read_parquet(path)
            print(f"Loaded cache {path} rows={len(native[res])}")
    if len(native) == 3:
        return fusion_frames_from_fetch(
            df5m, native["30m"], native["1h"], native["2h"]
        )
    frames: Dict[str, pd.DataFrame] = {"5m": df5m}
    frames.update(native)
    return frames


def _load_decision_times(path: Path) -> np.ndarray:
    frame = pd.read_parquet(path)
    if "time" not in frame.columns:
        raise ValueError(f"decision times parquet missing time: {path}")
    return pd.to_datetime(frame["time"], utc=True).to_numpy()


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def eval_fusion_checkpoint(
    checkpoint: Path,
    windows_dir: Path,
) -> Dict[str, Any]:
    """Score ``best.pt`` on cached val+test windows. Does not train.

    Args:
        checkpoint: ``best.pt`` written by ``train_mtf_fusion``.
        windows_dir: Directory with memmap windows and ``decision_times.parquet``.

    Returns:
        Dict with ``ok``, optional ``logits`` ``(n, H, C)`` and ``times``, or
        ``reason`` when NumPy/ONNX/Torch eval fails.
    """
    try:
        import torch

        from scripts.colab.mtf_fusion_model import (
            fusion_model_from_config,
        )
        from scripts.colab.mtf_fusion_research import (
            loader_runtime_kwargs,
            make_loader,
            predict_logits,
            purged_dev_test_split,
            try_load_fusion_dataset_cache,
        )
    except Exception as exc:  # noqa: BLE001 — checkpoint path is optional
        return {"ok": False, "reason": f"import_failed:{type(exc).__name__}:{exc}"}

    ckpt_path = Path(checkpoint)
    cache_path = Path(windows_dir)
    if not ckpt_path.is_file():
        return {"ok": False, "reason": f"missing_checkpoint:{ckpt_path}"}
    cfg = default_fusion_training_config()
    cached = try_load_fusion_dataset_cache(
        cache_path,
        stride=int(cfg["stride"]),
        window_lens=cfg.get("window_lens"),
        target_window_minutes=cfg.get("target_window_minutes"),
    )
    if cached is None:
        return {"ok": False, "reason": f"window_cache_mismatch:{cache_path}"}
    try:
        try:
            blob = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        except TypeError:
            blob = torch.load(ckpt_path, map_location="cpu")
        state = blob["state_dict"] if isinstance(blob, dict) and "state_dict" in blob else blob
        ckpt_cfg = dict(blob.get("config") or {}) if isinstance(blob, dict) else {}
        merge_cfg = dict(cfg)
        merge_cfg.update(ckpt_cfg)
        n_features = len(fusion_feature_cols_v14())
        device = torch.device("cpu")
        model = fusion_model_from_config(n_features, merge_cfg)
        model.load_state_dict(state)
        model.to(device)
        model.eval()
        splits = purged_dev_test_split(
            cached.windows,
            cached.labels,
            train_frac=float(merge_cfg.get("train_frac") or 0.70),
            val_frac=float(merge_cfg.get("val_frac") or 0.15),
            embargo_bars=int(merge_cfg.get("embargo_bars") or 24),
            candle_ids=cached.candle_ids,
            chart_ids=cached.chart_ids,
        )
        loader_kw = dict(loader_runtime_kwargs(merge_cfg, device))
        loader_kw["windows_in_ram"] = False
        loader_kw["num_workers"] = 0
        loader_kw["pin_memory"] = False
        batch = int(merge_cfg.get("batch_size") or 128)
        val_loader = make_loader(
            splits["val"]["windows"],
            splits["val"]["labels"],
            batch_size=batch,
            shuffle=False,
            candle_ids=splits["val"].get("candle_ids"),
            chart_ids=splits["val"].get("chart_ids"),
            **loader_kw,
        )
        test_loader = make_loader(
            splits["test"]["windows"],
            splits["test"]["labels"],
            batch_size=batch,
            shuffle=False,
            candle_ids=splits["test"].get("candle_ids"),
            chart_ids=splits["test"].get("chart_ids"),
            **loader_kw,
        )
        print("Scoring checkpoint on val+test windows (CPU, no train)...")
        val_logits, _val_y = predict_logits(model, val_loader, device)
        test_logits, _test_y = predict_logits(model, test_loader, device)
        n_win = len(cached.decision_times)
        slices = purged_index_slices(
            n_win,
            train_frac=float(merge_cfg.get("train_frac") or 0.70),
            val_frac=float(merge_cfg.get("val_frac") or 0.15),
            embargo_bars=int(merge_cfg.get("embargo_bars") or 24),
        )
        times = pd.to_datetime(cached.decision_times, utc=True)
        packed_times = np.concatenate(
            [
                times[slices["val"]].to_numpy(),
                times[slices["test"]].to_numpy(),
            ]
        )
        logits = np.concatenate([val_logits, test_logits], axis=0)
        if len(logits) != len(packed_times):
            return {
                "ok": False,
                "reason": f"logit_time_mismatch:{len(logits)}!={len(packed_times)}",
            }
        print(
            f"Checkpoint logits val={val_logits.shape} test={test_logits.shape}"
        )
        return {
            "ok": True,
            "logits": logits,
            "times": packed_times,
            "n_val": int(val_logits.shape[0]),
            "n_test": int(test_logits.shape[0]),
            "checkpoint": str(ckpt_path),
        }
    except Exception as exc:  # noqa: BLE001 — last-bar bake-off still ships
        return {"ok": False, "reason": f"{type(exc).__name__}:{exc}"}


def _print_readings(report: Dict[str, Any]) -> None:
    pack = report.get("direction_predictability") or {}
    horizons = pack.get("horizons") or {}
    rows = []
    for key, horizon in horizons.items():
        rows.append(
            {
                "horizon": key,
                "discovery": horizon.get("discovery_reading"),
                "confirmatory": horizon.get("confirmatory_reading"),
                "transformer_left_juice": horizon.get("transformer_left_juice"),
                "transformer_confusion": horizon.get("transformer_confusion", True)
                if horizon.get("transformer")
                else horizon.get("transformer_confusion", False),
            }
        )
    print(json.dumps({"direction_predictability_readings": rows}, indent=2))
    path = report.get("path_regression") or {}
    path_rows = []
    for key, horizon in (path.get("horizons") or {}).items():
        path_rows.append(
            {
                "horizon": key,
                "discovery": horizon.get("discovery_reading"),
                "confirmatory": horizon.get("confirmatory_reading"),
                "chosen": horizon.get("chosen"),
            }
        )
    if path_rows:
        print(json.dumps({"path_regression_readings": path_rows}, indent=2))


def _resolve_windows_dir(checkpoint: Optional[Path], explicit: Optional[Path]) -> Path:
    if explicit is not None:
        return Path(explicit)
    if checkpoint is None:
        return Path("export/mtf_fusion_v15/fusion_windows")
    guess = Path(checkpoint).parent / "fusion_windows"
    if guess.is_dir():
        return guess
    return Path(checkpoint).parent


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="v15 fusion diagnostics (no Transformer training)."
    )
    parser.add_argument("--parquet", type=Path, default=None)
    parser.add_argument("--history-days", type=int, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("export/fusion_diagnostics/report.json"),
    )
    parser.add_argument("--index-samples", type=int, default=100)
    parser.add_argument("--truncation-samples", type=int, default=20)
    parser.add_argument("--knn-train-cap", type=int, default=8000)
    parser.add_argument("--knn-val-cap", type=int, default=2000)
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument(
        "--score-test",
        action="store_true",
        help="Unweighted last-bar bake-off with one confirmatory test pass.",
    )
    parser.add_argument(
        "--ablate-groups",
        action="store_true",
        help="Val-only knockout, add-one-in, and vol+time null.",
    )
    parser.add_argument(
        "--transformer-report",
        type=Path,
        default=None,
        help="direction_only_report.json (acc/F1/ECE; not a stop token).",
    )
    parser.add_argument(
        "--decision-times",
        type=Path,
        default=None,
        help="Stride-4 decision_times.parquet for aligned test rows.",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Optional best.pt for confusion/AUC (no retrain).",
    )
    parser.add_argument(
        "--windows-dir",
        type=Path,
        default=None,
        help="Window cache for checkpoint eval (default: fusion_windows).",
    )
    parser.add_argument(
        "--class-weight-sensitivity",
        action="store_true",
        help="Extra val fit with per-horizon inverse-frequency weights.",
    )
    parser.add_argument(
        "--forward-holdout",
        action="store_true",
        help="Record a skipped forward holdout (no tune on post-export bars).",
    )
    parser.add_argument(
        "--path-regression",
        action="store_true",
        help="Last-bar signed path-edge regression bake-off (no fused retrain).",
    )
    args = parser.parse_args(argv)

    cfg = default_fusion_training_config()
    history_days = int(args.history_days or cfg.get("history_days") or 900)
    out_path = Path(args.output)
    cache_dir = out_path.parent
    cache_path = cache_dir / "btcusd_5m_raw.parquet"
    df5m = _load_parquet_or_fetch(
        args.parquet,
        history_days=history_days,
        base_url=str(cfg.get("base_url") or "https://api.india.delta.exchange"),
        cache_path=cache_path,
    )
    frames = _load_htf_frames(cache_dir, df5m)

    transformer_test = None
    if args.transformer_report is not None:
        transformer_test = _load_json(Path(args.transformer_report))
        print(
            "transformer report experiment=",
            transformer_test.get("experiment"),
            "use_class_weights=",
            transformer_test.get("use_class_weights"),
        )

    decision_times = None
    if args.decision_times is not None:
        decision_times = _load_decision_times(Path(args.decision_times))
        print(f"Loaded decision times n={len(decision_times)}")

    xf_logits = None
    xf_times = None
    xf_meta: Dict[str, Any] = {"ok": False, "skipped": True}
    if args.checkpoint is not None:
        windows_dir = _resolve_windows_dir(args.checkpoint, args.windows_dir)
        xf_meta = eval_fusion_checkpoint(Path(args.checkpoint), windows_dir)
        if xf_meta.get("ok"):
            xf_logits = xf_meta.pop("logits")
            xf_times = xf_meta.pop("times")
            if decision_times is None:
                decision_times = xf_times
            print("Checkpoint confusion eval ok")
        else:
            print(
                "Checkpoint eval failed; last-bar decomp still ships. "
                f"reason={xf_meta.get('reason')}"
            )

    report = run_fusion_diagnostics(
        df5m,
        frames=frames,
        n_index_samples=int(args.index_samples),
        n_truncation_samples=int(args.truncation_samples),
        knn_train_cap=int(args.knn_train_cap),
        knn_val_cap=int(args.knn_val_cap),
        fit_simple_models=not bool(args.skip_models),
        score_test=bool(args.score_test),
        ablate_groups=bool(args.ablate_groups),
        transformer_test=transformer_test,
        decision_times=decision_times,
        transformer_window_logits=xf_logits,
        transformer_window_times=xf_times,
        class_weight_sensitivity=bool(args.class_weight_sensitivity),
        score_path_regression=bool(args.path_regression),
    )
    report["transformer_checkpoint_eval"] = {
        k: v for k, v in xf_meta.items() if k not in ("logits", "times")
    }
    if args.forward_holdout:
        last_t = pd.to_datetime(df5m["time"], utc=True).max()
        report["forward_holdout"] = {
            "ok": False,
            "skipped": True,
            "reason": "not_fetched",
            "labeled_end": str(last_t),
            "note": "Frozen models only; do not tune on a later holdout.",
        }
    pack = report.get("direction_predictability")
    if isinstance(pack, dict):
        pack["transformer_checkpoint_eval"] = report["transformer_checkpoint_eval"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("branch", report.get("branch"), "(diagnostics token, not the bake-off)")
    _print_readings(report)
    print(
        json.dumps(
            {"branch": report.get("branch"), "notes": report.get("notes")},
            indent=2,
        )
    )
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
