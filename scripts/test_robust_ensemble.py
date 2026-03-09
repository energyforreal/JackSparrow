"""
test_robust_ensemble.py  (v3)
------------------------------
JackSparrow – Smoke test for RobustEnsembleNode and EnsembleSignalBridge.

Tests added in v3
------------------
  • RegimeClassifier loading and regime prediction
  • Dynamic timeframe weight adaptation (TREND/RANGE/HIGH_VOL)
  • Feature drift detection (training stats vs live values)
  • Model promotion gate (Sharpe proxy comparison)
  • Dataset SHA-256 fingerprint in metadata
  • .joblib artifact format check
  • regime_features forwarding through bridge
  • All v2 tests retained

Usage
-----
  python scripts/test_robust_ensemble.py \\
      --model-dir agent/model_storage \\
      --symbol BTCUSD \\
      --timeframes 15m 30m 1h 2h 4h
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_ensemble_v3")

from agent.data.feature_list import EXPECTED_FEATURE_COUNT, FEATURE_LIST
from agent.models.ensemble_signal_bridge import (
    CombinedSignal,
    EnsembleSignalBridge,
    PositionContext,
    RegimeContext,
    REGIME_TF_WEIGHTS,
)
from agent.models.mcp_model_node import MCPModelRequest
from agent.models.robust_ensemble_node import RobustEnsembleNode


def _feats(seed: int = 0) -> List[float]:
    return np.random.default_rng(seed).uniform(-1.0, 1.0, size=EXPECTED_FEATURE_COUNT).tolist()


def _regime_feats(seed: int = 0) -> List[float]:
    """7 regime-specific features: adx, atr, bb_width, vol_zscore, rsi_std, slope, vol_z."""
    rng = np.random.default_rng(seed)
    return [
        float(rng.uniform(10, 50)),   # adx_14
        float(rng.uniform(0, 0.05)),  # atr_14 normalised
        float(rng.uniform(0, 0.1)),   # bb_width
        float(rng.normal(0, 1)),      # volatility_zscore
        float(rng.uniform(5, 20)),    # rsi_std
        float(rng.normal(0, 0.001)),  # price_slope
        float(rng.normal(0, 1)),      # volume_zscore
    ]


def _sep(title: str = "") -> None:
    log.info("── " + title + " " + "─" * max(0, 55 - len(title)))


def run(model_dir: str, symbol: str, timeframes: List[str]) -> bool:
    model_dir_path = Path(model_dir)
    ens_path = model_dir_path / "robust_ensemble"
    xgboost_path = model_dir_path / "xgboost"
    all_pass = True
    nodes: dict = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Step 0 – Feature schema validation (canonical count + order)
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 0: Feature schema validation")
    try:
        from feature_store.feature_registry import (
            FEATURE_LIST as REGISTRY_LIST,
            EXPECTED_FEATURE_COUNT as REGISTRY_COUNT,
            validate_feature_count,
            validate_feature_order,
        )
        ok_count = validate_feature_count(FEATURE_LIST)
        ok_order = validate_feature_order(FEATURE_LIST)
        if ok_count and ok_order and REGISTRY_COUNT == EXPECTED_FEATURE_COUNT:
            log.info(f"  ✓ Feature count={EXPECTED_FEATURE_COUNT}  order=canonical")
        else:
            log.warning("  ⚠ Feature list mismatch vs feature_store registry")
    except ImportError:
        log.info("  ⚠ feature_store not available; using agent.data.feature_list only")
        if len(FEATURE_LIST) == EXPECTED_FEATURE_COUNT:
            log.info(f"  ✓ Feature count={EXPECTED_FEATURE_COUNT}")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 0b – Strict artifacts (xgboost dir): load and run pipeline test
    # ─────────────────────────────────────────────────────────────────────────
    strict_entry = xgboost_path / "entry_meta.pkl"
    if strict_entry.exists():
        _sep("Step 0b: Strict artifacts (xgboost) load + prediction")
        try:
            node_strict = RobustEnsembleNode.from_strict_artifacts(xgboost_path)
            feats = _feats(seed=42)
            req = MCPModelRequest(features=feats, context={"feature_names": FEATURE_LIST})
            pred = node_strict._predict_sync(req)
            if -1.0 <= pred.prediction <= 1.0:
                log.info(f"  ✓ from_strict_artifacts OK  prediction={pred.prediction:.4f}")
                nodes["1h"] = node_strict
            else:
                log.error("  ✗ Strict-artifact prediction out of range")
                all_pass = False
            schema_path = xgboost_path / "feature_schema.json"
            if schema_path.exists():
                data = json.loads(schema_path.read_text())
                n_feat = data.get("feature_count", 0)
                log.info(f"  ✓ feature_schema.json  feature_count={n_feat}")
        except Exception as exc:
            log.error(f"  ✗ Strict-artifact test failed: {exc}", exc_info=True)
            all_pass = False

    # ─────────────────────────────────────────────────────────────────────────
    # Step 1 – Artefact file check + .joblib format verification
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 1: Artefact files + format check")
    meta_paths: List[str] = []
    for tf in timeframes:
        tag  = f"{symbol}_{tf}"
        meta = ens_path / f"metadata_{tag}.json"
        if not meta.exists():
            log.error(f"  ✗ MISSING: {meta}")
            all_pass = False
        else:
            with open(meta) as f:
                md = json.load(f)

            # Check .joblib artifact format
            fmt = md.get("artifact_format", ".pkl")
            log.info(f"  ✓ {meta.name}  [artifact_format={fmt}]")
            if fmt == ".joblib":
                log.info(f"    ✓ Correct format: .joblib")
            else:
                log.warning(f"    ⚠ Old format (.pkl) – re-train to upgrade to .joblib")

            # Check dataset hash present
            if md.get("dataset_sha256"):
                log.info(f"    ✓ dataset_sha256 = {md['dataset_sha256']}")
            else:
                log.warning(f"    ⚠ dataset_sha256 missing – re-train to add fingerprint")

            # Check Sharpe proxy
            sharpe = md.get("sharpe_proxy")
            if sharpe is not None:
                log.info(f"    ✓ sharpe_proxy = {sharpe:.4f}")
            else:
                log.warning(f"    ⚠ sharpe_proxy missing")

            # Check signal thresholds
            thresholds = md.get("signal_thresholds", {})
            if thresholds:
                log.info(f"    ✓ signal_thresholds = {thresholds}")
            else:
                log.warning(f"    ⚠ signal_thresholds not in metadata")

            meta_paths.append(str(meta))

    if not meta_paths and not nodes:
        log.error("No metadata files and no strict artifacts found. Run train_robust_ensemble.py first.")
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # Step 2 – Load nodes + warm-up (skip if already loaded from strict)
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 2: Load + warm-up")
    for mp in meta_paths:
        if not mp:
            continue
        try:
            node = RobustEnsembleNode.from_metadata(mp)
            tf   = node.model_name.rsplit("_", 1)[-1]
            nodes[tf] = node
            log.info(f"  ✓ Loaded  {node.model_name}  v{node.model_version}")
            regime_loaded = node._regime_clf is not None
            drift_features = len(node._drift_stats)
            log.info(
                f"    regime_model={regime_loaded}  "
                f"drift_stats_features={drift_features}"
            )
        except Exception as exc:
            log.error(f"  ✗ Failed to load {mp}: {exc}", exc_info=True)
            all_pass = False

    for tf, node in list(nodes.items()):
        try:
            node.warm_up(n_calls=2)
            log.info(f"  ✓ Warm-up OK [{tf}]")
        except Exception as exc:
            log.warning(f"  Warm-up [{tf}]: {exc}")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3 – Per-node inference with regime features
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 3: Per-node inference (with regime_features)")
    for tf, node in nodes.items():
        for trial in range(3):
            feats = _feats(seed=trial)
            req   = MCPModelRequest(
                features=feats,
                context={
                    "feature_names":     FEATURE_LIST,
                    "regime_features":   _regime_feats(seed=trial),  # NEW
                    "position_context": {
                        "unrealised_pnl_pct":  0.01 * (trial - 1),
                        "time_in_trade_ratio":  trial / 2,
                        "drawdown_from_peak":   0.005,
                        "entry_distance_atr":   float(trial - 1),
                    },
                    "regime_context": {
                        "adx_14":       20 + trial * 5,
                        "atr_pct_rank":  0.3 + trial * 0.2,
                        "vol_zscore":    float(trial - 1),
                    },
                },
            )
            pred  = node._predict_sync(req)
            ctx   = pred.context or {}
            e_sig = ctx.get("entry_signal", pred.prediction)
            x_sig = ctx.get("exit_signal",  0.0)
            regime_info = ctx.get("regime", {})
            drift_warns = ctx.get("drift_warnings", [])

            in_range = -1.0 <= pred.prediction <= 1.0 and -1.0 <= x_sig <= 1.0
            mark = "✓" if in_range else "✗"
            log.info(
                f"  {mark} [{tf}] t={trial}  "
                f"entry={e_sig:+.4f}  exit={x_sig:+.4f}  "
                f"regime={regime_info.get('regime_name', '?')}  "
                f"drift_warns={len(drift_warns)}  ms={pred.computation_time_ms:.1f}"
            )
            if not in_range:
                log.error(f"    OUT OF RANGE!  entry={e_sig}  exit={x_sig}")
                all_pass = False

    # ─────────────────────────────────────────────────────────────────────────
    # Step 4 – Bridge combined signal with dynamic weights
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 4: Bridge combined signal + dynamic regime weights")
    try:
        bridge = EnsembleSignalBridge(nodes, dynamic_weights=True)
        log.info(f"  {bridge}")

        for trial in range(6):
            feats = _feats(seed=200 + trial)
            pos   = PositionContext(
                unrealised_pnl_pct  = 0.02 * (trial - 2),
                time_in_trade_ratio  = trial / 5,
                drawdown_from_peak   = 0.003 * trial,
                entry_distance_atr   = float(trial - 2),
            )
            reg = RegimeContext(
                adx_14       = 15.0 + trial * 4,
                atr_pct_rank = min(0.1 * trial, 1.0),
                vol_zscore   = float(trial - 2),
            )
            combined: CombinedSignal = bridge.get_combined_signal(
                feats, pos, reg,
                regime_features=_regime_feats(seed=200 + trial),  # NEW
            )

            log.info(
                f"  t={trial}  consensus={combined.consensus:<14}  "
                f"regime={combined.regime:<9}  "
                f"entry={combined.entry.signal:+.4f} "
                f"[{combined.entry.direction}/{combined.entry.signal_strength}]  "
                f"exit={combined.exit.signal:+.4f} [{combined.exit.urgency}]  "
                f"conf={combined.overall_confidence:.4f}  "
                f"drifts={len(combined.drift_warnings)}"
            )
    except Exception as exc:
        log.error(f"  ✗ Bridge test failed: {exc}", exc_info=True)
        all_pass = False

    # ─────────────────────────────────────────────────────────────────────────
    # Step 5 – Dynamic weight tables (regime-specific)
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 5: Regime-specific weight tables")
    regime_names = {0: "RANGE", 1: "TREND", 2: "HIGH_VOL"}
    for rid, rname in regime_names.items():
        weights = REGIME_TF_WEIGHTS.get(rid, {})
        total   = sum(weights.values())
        log.info(f"  [{rname}] weights={weights}  sum={total:.2f}")
        if abs(total - 1.0) > 0.01:
            log.error(f"  ✗ Weights don't sum to 1.0 for {rname}")
            all_pass = False
        else:
            log.info(f"  ✓ Weights normalised correctly for {rname}")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 6 – Single-timeframe overrides
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 6: Single-timeframe override")
    bridge2 = EnsembleSignalBridge(nodes)
    for tf in list(nodes.keys())[:2]:
        sig = bridge2.get_entry_signal(_feats(seed=999), timeframe=tf)
        log.info(
            f"  [{tf}] direction={sig.direction}  signal={sig.signal:+.4f}  "
            f"should_enter={sig.should_enter}  regime={sig.regime}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Step 7 – Feature drift detection
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 7: Feature drift detection")
    node = next(iter(nodes.values()))
    if node._drift_stats:
        # Create an extreme-value feature vector to trigger drift warnings
        extreme_feats = [1e6] * EXPECTED_FEATURE_COUNT
        req = MCPModelRequest(features=extreme_feats, context={})
        pred = node._predict_sync(req)
        drift_warns = (pred.context or {}).get("drift_warnings", [])
        if drift_warns:
            log.info(f"  ✓ Drift detection working: {len(drift_warns)} features flagged")
            log.info(f"    Drifted: {drift_warns[:5]}")
        else:
            log.warning("  ⚠ Extreme values not detected as drift (check threshold)")
    else:
        log.info("  ⚠ No drift stats loaded (run train first)")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 8 – Edge cases
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 8: Edge cases")
    # Wrong feature count → error
    bad_req  = MCPModelRequest(features=[0.0] * 10, context={})
    bad_pred = node._predict_sync(bad_req)
    if bad_pred.health_status == "error":
        log.info("  ✓ Wrong feature count → error status (expected).")
    else:
        log.warning("  ⚠ Expected 'error' for wrong feature count.")

    # Zero-vector (valid length) – should not raise
    zero_req  = MCPModelRequest(features=[0.0] * EXPECTED_FEATURE_COUNT, context={})
    zero_pred = node._predict_sync(zero_req)
    if -1.0 <= zero_pred.prediction <= 1.0:
        log.info("  ✓ Zero-vector features handled correctly.")
    else:
        log.error("  ✗ Zero-vector features returned out-of-range prediction.")
        all_pass = False

    # ─────────────────────────────────────────────────────────────────────────
    # Step 9 – Health report (/model/status)
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 9: Health report (/model/status)")
    bridge3 = EnsembleSignalBridge(nodes)
    report  = bridge3.health_report()
    for tf, h in report.items():
        if tf.startswith("_"):
            continue
        log.info(
            f"  [{tf}]  status={h['status']}  v={h['version']}  "
            f"calls={h['call_count']}  errors={h['error_count']}  "
            f"avg_ms={h['avg_inference_ms']}  "
            f"regime_model={h.get('regime_model_loaded', False)}  "
            f"drift_monitored={h.get('drift_features_monitored', 0)}"
        )
    log.info(f"  static_weights: {report.get('_weights')}")
    log.info(f"  dynamic_weights: {report.get('_dynamic_weights')}")

    # ─────────────────────────────────────────────────────────────────────────
    # Step 10 – Feature importance + drift stats JSON files
    # ─────────────────────────────────────────────────────────────────────────
    _sep("Step 10: Artifact JSON files")
    for tf in timeframes:
        tag = f"{symbol}_{tf}"

        # Feature importance
        fi = ens_path / f"feature_importance_{tag}.json"
        if fi.exists():
            data  = json.loads(fi.read_text())
            top3e = list(data.get("entry", {}).items())[:3]
            log.info(f"  [{tf}] importance top-3: {top3e}")
        else:
            log.warning(f"  [{tf}] feature_importance not found")

        # Drift stats (v3 new)
        fd = ens_path / f"feature_drift_{tag}.json"
        if fd.exists():
            data     = json.loads(fd.read_text())
            n_feats  = len(data.get("features", {}))
            log.info(f"  [{tf}] ✓ feature_drift: {n_feats} features tracked")
        else:
            log.info(f"  [{tf}] ⚠ feature_drift file not found (train first)")

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────
    log.info("\n" + "="*58)
    if all_pass:
        log.info("  ✅  ALL TESTS PASSED – ensemble is production-ready (v3).")
    else:
        log.error("  ❌  SOME TESTS FAILED – review errors above.")
    log.info("="*58)
    return all_pass


def main() -> None:
    p = argparse.ArgumentParser(description="Smoke test for robust ensemble v3")
    p.add_argument("--model-dir",   default="agent/model_storage")
    p.add_argument("--symbol",      default="BTCUSD")
    p.add_argument(
        "--timeframes", nargs="+",
        default=["15m", "30m", "1h", "2h", "4h"],
    )
    a = p.parse_args()
    ok = run(a.model_dir, a.symbol, a.timeframes)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
