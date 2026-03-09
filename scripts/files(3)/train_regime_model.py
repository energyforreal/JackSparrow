"""
train_regime_model.py  (v3 – NEW)
-----------------------------------
JackSparrow – Regime Model Trainer

Trains the two-stage regime-aware system on top of the existing ensemble:
  1. RegimeClassifier  (TREND / RANGE / HIGH_VOL detector)
  2. 3× Regime-Specific Entry Models

This script can be run standalone AFTER train_robust_ensemble.py has produced
features and labels, OR it can be integrated into the main training loop.

The regime models use the same data pipeline as the main ensemble but with
a narrower 7-feature input (regime features) for the classifier stage.

Artefacts produced (per timeframe)
------------------------------------
  models/robust_ensemble/regime_model_{TAG}.joblib
  models/robust_ensemble/regime_scaler_{TAG}.joblib
  models/robust_ensemble/entry_regime_scaler_{TAG}.joblib
  models/robust_ensemble/entry_trend_{TAG}.joblib
  models/robust_ensemble/entry_range_{TAG}.joblib
  models/robust_ensemble/entry_vol_{TAG}.joblib
  models/robust_ensemble/regime_metadata_{TAG}.json

Usage
-----
  python scripts/train_regime_model.py \\
      --symbol BTCUSD \\
      --timeframes 15m 30m 1h 2h 4h \\
      --total-candles 6000 \\
      --n-folds 5 \\
      --output-dir agent/model_storage

Required env vars
-----------------
  DELTA_EXCHANGE_API_KEY
  DELTA_EXCHANGE_API_SECRET
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("train_regime")

from agent.data.delta_client import DeltaExchangeClient
from agent.data.feature_engineering import FeatureEngineering
from agent.data.feature_list import EXPECTED_FEATURE_COUNT, FEATURE_LIST
from agent.models.regime_classifier import (
    RegimeModelTrainer,
    RegimeTrainingConfig,
    compute_feature_drift_stats,
    drift_stats_to_dict,
    evaluate_sharpe_proxy,
    extract_regime_features,
    make_regime_labels,
    should_promote_model,
)

# Re-use the rate limiter and candle fetch from the main training script
from train_robust_ensemble import (
    TrainingConfig,
    _RATE_LIMITER,
    compute_features,
    fetch_candles,
    make_entry_labels,
)


# ─────────────────────────────────────────────────────────────────────────────
# Per-timeframe pipeline
# ─────────────────────────────────────────────────────────────────────────────

def train_regime_for_timeframe(
    client:     DeltaExchangeClient,
    cfg:        TrainingConfig,
    reg_cfg:    RegimeTrainingConfig,
    timeframe:  str,
    output_dir: Path,
) -> Dict:
    tag = f"{cfg.symbol}_{timeframe}"
    log.info(f"\n  ── Regime training: {tag} ──")

    # 1. Fetch candles
    df = fetch_candles(client, cfg.symbol, timeframe, cfg.total_candles)

    # 2. Compute features
    log.info("  Computing features …")
    feat_df = compute_features(df)

    warmup = 200
    feat_df = feat_df.iloc[warmup:].reset_index(drop=True)
    df      = df.iloc[warmup:].reset_index(drop=True)
    feat_df = feat_df.ffill().fillna(0.0)

    close = df["close"]

    # 3. Entry labels
    entry_lbl = make_entry_labels(close, threshold=cfg.entry_threshold)

    # 4. Trim last lookahead rows
    valid     = len(feat_df) - cfg.exit_lookahead
    feat_df   = feat_df.iloc[:valid]
    close     = close.iloc[:valid]
    entry_lbl = entry_lbl.iloc[:valid]

    # 5. Feature drift statistics (saved alongside regime models)
    log.info("  Computing feature drift statistics …")
    drift_stats  = compute_feature_drift_stats(feat_df, FEATURE_LIST)
    drift_dict   = drift_stats_to_dict(drift_stats)

    # 6. Train regime models
    trainer = RegimeModelTrainer(reg_cfg)
    ens_dir = output_dir / "robust_ensemble"
    meta    = trainer.train(feat_df, close, entry_lbl, tag, ens_dir)

    # 7. Compute Sharpe proxy for model promotion gate
    n      = len(feat_df)
    te_idx = int(n * (reg_cfg.train_split + reg_cfg.val_split))

    try:
        from agent.models.regime_classifier import (
            REGIME_NAMES, RegimeClassifier, extract_regime_features
        )
        classifier  = RegimeClassifier.from_metadata(
            ens_dir / f"regime_metadata_{tag}.json"
        )
        reg_feat_df = extract_regime_features(feat_df, close)
        X_te_reg    = reg_feat_df.values[te_idx:]
        X_te_entry  = feat_df.values[te_idx:]
        close_te    = close.values[te_idx:]
        y_te_entry  = entry_lbl.values[te_idx:]

        probas = []
        for i in range(len(X_te_reg)):
            regime_id = classifier.predict_regime(X_te_reg[i].tolist())
            proba     = classifier.predict_entry(X_te_entry[i].tolist(), regime_id)
            probas.append(proba)
        probas = np.array(probas)

        sharpe = evaluate_sharpe_proxy(probas, y_te_entry, close_te)
        log.info(f"  Regime-aware Sharpe proxy (test): {sharpe:.4f}")
    except Exception as exc:
        log.warning(f"  Sharpe proxy computation failed: {exc}")
        sharpe = 0.0

    # 8. Model promotion check
    baseline_path = ens_dir / f"regime_metadata_{tag}.json"
    promo = should_promote_model(sharpe, baseline_path if baseline_path.exists() else None)
    log.info(f"  Promotion: {promo.reason}")

    # 9. Append drift stats and Sharpe to metadata
    meta_path = ens_dir / f"regime_metadata_{tag}.json"
    with open(meta_path) as f:
        meta_doc = json.load(f)

    meta_doc["feature_drift_stats"]   = drift_dict
    meta_doc["sharpe_proxy"]          = round(sharpe, 4)
    meta_doc["promotion"]             = {
        "promoted":       promo.promoted,
        "new_score":      promo.new_score,
        "baseline_score": promo.baseline_score,
        "reason":         promo.reason,
    }
    meta_doc["dataset_sha256"] = _hash_features(feat_df)

    with open(meta_path, "w") as f:
        json.dump(meta_doc, f, indent=2, default=str)

    log.info(f"  Regime metadata updated: {meta_path.name}")
    return meta_doc


def _hash_features(feat_df: pd.DataFrame) -> str:
    """Compute a SHA-256 fingerprint of the feature matrix for reproducibility."""
    import hashlib
    h = hashlib.sha256(
        feat_df.values.astype(np.float32).tobytes()
    ).hexdigest()[:16]
    return h


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="JackSparrow – Regime Model Trainer v3")
    p.add_argument("--symbol",          default="BTCUSD")
    p.add_argument("--timeframes", nargs="+", default=["15m", "30m", "1h", "2h", "4h"])
    p.add_argument("--total-candles",   type=int,   default=6000)
    p.add_argument("--n-folds",         type=int,   default=5)
    p.add_argument("--entry-threshold", type=float, default=0.003)
    p.add_argument("--exit-lookahead",  type=int,   default=8)
    p.add_argument("--output-dir",      default="agent/model_storage")
    p.add_argument("--adx-trend",       type=float, default=25.0)
    p.add_argument("--atr-vol-pct",     type=float, default=80.0)
    p.add_argument("--seed",            type=int,   default=42)
    return p.parse_args()


def main() -> None:
    args = parse_args()

    api_key    = os.environ.get("DELTA_EXCHANGE_API_KEY", "")
    api_secret = os.environ.get("DELTA_EXCHANGE_API_SECRET", "")
    if not api_key or not api_secret:
        log.error("DELTA_EXCHANGE_API_KEY or DELTA_EXCHANGE_API_SECRET not set.")
        sys.exit(1)

    client = DeltaExchangeClient(api_key=api_key, api_secret=api_secret)

    cfg = TrainingConfig(
        symbol          = args.symbol,
        timeframes      = args.timeframes,
        total_candles   = args.total_candles,
        entry_threshold = args.entry_threshold,
        exit_lookahead  = args.exit_lookahead,
        output_dir      = args.output_dir,
        random_seed     = args.seed,
    )
    reg_cfg = RegimeTrainingConfig(
        n_folds              = args.n_folds,
        seed                 = args.seed,
        adx_trend_threshold  = args.adx_trend,
        atr_vol_percentile   = args.atr_vol_pct,
    )

    output_dir = PROJECT_ROOT / args.output_dir
    results = []

    log.info("JackSparrow – Regime Model Trainer  v3.0.0")
    log.info(f"  Symbol     : {args.symbol}")
    log.info(f"  Timeframes : {args.timeframes}")

    for tf in args.timeframes:
        try:
            result = train_regime_for_timeframe(client, cfg, reg_cfg, tf, output_dir)
            results.append(result)
        except Exception as exc:
            log.error(f"  ✗ Failed [{args.symbol} {tf}]: {exc}", exc_info=True)

    log.info("\n" + "="*60)
    log.info("  REGIME TRAINING COMPLETE")
    log.info("="*60)
    for r in results:
        m = r.get("regime_classifier_metrics", {})
        log.info(
            f"  {r.get('tag', '?'):<24}  "
            f"regime_acc={m.get('accuracy', 0):.3f}  "
            f"sharpe={r.get('sharpe_proxy', 0):.4f}  "
            f"promoted={r.get('promotion', {}).get('promoted', False)}"
        )


if __name__ == "__main__":
    main()
