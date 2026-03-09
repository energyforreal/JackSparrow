"""
robust_ensemble_node.py  (v3)
------------------------------
JackSparrow – Robust Stacking Ensemble MCP Model Node

Changes from v2 (audit-driven)
--------------------------------
  [NEW]  RegimeClassifier integration: regime detected first, routes to
         regime-specific entry model when regime artifacts are present
  [NEW]  Signal thresholds imported from train_robust_ensemble (single source of truth)
  [NEW]  Live feature drift detection against training distribution stats
  [NEW]  Artifacts loaded as .joblib (backward-compatible .pkl fallback retained)
  [NEW]  Lazy artefact loading: each model loaded once on first access
  [FIX]  All v2 improvements retained

Signal contract
---------------
  prediction                → ENTRY signal  [-1.0, +1.0]  (sell ↔ buy)
  context["exit_signal"]    → EXIT  signal  [-1.0, +1.0]  (hold ↔ close)
  context["entry_proba"]    → {sell, hold, buy} probabilities
  context["exit_proba"]     → {hold, exit}  probabilities
  context["entry_confidence"]  [0, 1]
  context["exit_confidence"]   [0, 1]
  context["regime"]            {id, name, proba}  (when regime model loaded)
  context["drift_warnings"]    list of drifted feature names

Discovery
---------
  Drop artefacts in agent/model_storage/robust_ensemble/
  and add "model_node_class": "RobustEnsembleNode" to each metadata_{TAG}.json.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    import joblib
    def _load(p): return joblib.load(p)
except ImportError:
    import pickle
    def _load(p):
        with open(p, "rb") as f: return pickle.load(f)

from agent.data.feature_list import EXPECTED_FEATURE_COUNT, FEATURE_LIST
from agent.models.mcp_model_node import (
    MCPModelNode,
    MCPModelPrediction,
    MCPModelRequest,
)

log = logging.getLogger(__name__)

# ── Centralised thresholds (imported so node and bridge agree) ─────────────────
try:
    from train_robust_ensemble import ENTRY_THRESHOLD, EXIT_THRESHOLD
except ImportError:
    ENTRY_THRESHOLD: float = 0.20
    EXIT_THRESHOLD:  float = 0.25


# ─────────────────────────────────────────────────────────────────────────────
# Position and regime context containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PositionContext:
    """Live position state fed to the exit model at inference time."""
    unrealised_pnl_pct:   float = 0.0
    time_in_trade_ratio:  float = 0.0
    drawdown_from_peak:   float = 0.0
    entry_distance_atr:   float = 0.0


@dataclass
class RegimeContext:
    """Market-regime features fed to the exit model at inference time.

    If not supplied the values trained at simulation time are used (neutral).
    """
    adx_14:          float = 25.0
    atr_pct_rank:    float = 0.5
    vol_zscore:      float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Signal normalisation (centralised)
# ─────────────────────────────────────────────────────────────────────────────

def _entry_signal(proba: np.ndarray) -> Tuple[float, float]:
    """3-class probability → directional signal in [-1, +1] and confidence."""
    p_sell, p_hold, p_buy = float(proba[0]), float(proba[1]), float(proba[2])
    eps    = 1e-9
    signal = (p_buy - p_sell) / (p_buy + p_sell + eps) * (1.0 - p_hold)
    return float(np.clip(signal, -1.0, 1.0)), max(p_sell, p_hold, p_buy)


def _exit_signal(proba: np.ndarray) -> Tuple[float, float]:
    """Binary exit probability → [-1, +1] signal."""
    p_exit = float(proba[1])
    signal = float(np.clip(2.0 * p_exit - 1.0, -1.0, 1.0))
    return signal, abs(signal)


def _build_reasoning(
    feat_names: List[str],
    feat_vals: List[float],
    importance: Dict[str, float],
    entry_signal: float,
    entry_conf: float,
    exit_signal: float,
    exit_conf: float,
    regime_name: str = "UNKNOWN",
    drift_warnings: List[str] = [],
) -> str:
    direction = (
        "BUY"  if entry_signal > ENTRY_THRESHOLD else
        "SELL" if entry_signal < -ENTRY_THRESHOLD else "HOLD"
    )
    exit_act = "EXIT" if exit_signal > EXIT_THRESHOLD else "HOLD POSITION"
    top = [(n, w) for n, w in list(importance.items())[:5] if n in feat_names]
    feat_str = ", ".join(
        f"{n}={feat_vals[feat_names.index(n)]:.4g}[w={w:.3f}]"
        for n, w in top
    )
    drift_str = f"  ⚠ DRIFT: {drift_warnings[:3]}" if drift_warnings else ""
    return (
        f"Regime: {regime_name}  "
        f"Entry: {entry_signal:+.3f} ({direction}, conf={entry_conf:.2f})  "
        f"Exit: {exit_signal:+.3f} ({exit_act}, conf={exit_conf:.2f})  "
        f"Drivers: {feat_str}{drift_str}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Drift detection helper
# ─────────────────────────────────────────────────────────────────────────────

def _check_drift(
    features: List[float],
    feature_names: List[str],
    drift_stats: Dict[str, Dict],
    threshold_sigma: float = 4.0,
) -> List[str]:
    """Return names of features that exceed the drift threshold."""
    drifted = []
    for name, val in zip(feature_names, features):
        stat = drift_stats.get(name)
        if stat is None:
            continue
        std = stat.get("std", 0.0)
        if std < 1e-12:
            continue
        z = abs((val - stat["mean"]) / std)
        if z > threshold_sigma:
            drifted.append(name)
    return drifted


# ─────────────────────────────────────────────────────────────────────────────
# Node
# ─────────────────────────────────────────────────────────────────────────────

class RobustEnsembleNode(MCPModelNode):
    """MCP Model Node wrapping the stacking ensemble (v3).

    Regime-aware prediction
    -----------------------
    If regime model artifacts are present alongside the base ensemble, the node:
      1. Extracts 7 regime features from context["regime_features"]
      2. Detects market regime (TREND / RANGE / HIGH_VOL)
      3. Routes to the regime-specific entry model for that regime
      4. Falls back to the base stacking ensemble if regime model unavailable

    Feature drift detection
    -----------------------
    If feature_drift_{tag}.json is present, live features are checked against
    training distribution stats.  Drifted features are logged and reported
    in context["drift_warnings"].
    """

    _cache: Dict[str, "RobustEnsembleNode"] = {}

    def __init__(
        self,
        model_name:    str,
        model_version: str,
        entry_base:    Dict[str, Any],
        entry_meta:    Any,
        entry_scaler:  Any,
        exit_base:     Dict[str, Any],
        exit_meta:     Any,
        exit_scaler:   Any,
        metadata:      Dict[str, Any],
        drift_stats:   Optional[Dict[str, Dict]] = None,
        regime_classifier: Optional[Any] = None,
    ) -> None:
        self.model_name    = model_name
        self.model_version = model_version

        self._entry_base   = entry_base
        self._entry_meta   = entry_meta
        self._entry_scaler = entry_scaler
        self._exit_base    = exit_base
        self._exit_meta    = exit_meta
        self._exit_scaler  = exit_scaler
        self._metadata     = metadata
        self._drift_stats  = drift_stats or {}
        self._regime_clf   = regime_classifier   # RegimeClassifier or None

        self._feature_names: List[str] = metadata.get("features_required", FEATURE_LIST)
        self._exit_feature_names: List[str] = metadata.get(
            "exit_feature_names",
            FEATURE_LIST + [
                "sim_unrealised_pnl_pct", "sim_time_in_trade_ratio",
                "sim_drawdown_from_peak", "sim_entry_distance_atr",
                "regime_adx_14", "regime_atr_pct_rank", "regime_vol_zscore",
            ],
        )
        self._entry_importance: Dict[str, float] = metadata.get("entry_feature_importance", {})
        self._exit_importance:  Dict[str, float] = metadata.get("exit_feature_importance",  {})

        self._health_status  = "healthy"
        self._call_count     = 0
        self._total_ms       = 0.0
        self._error_count    = 0

        regime_loaded = self._regime_clf is not None
        log.info(
            f"RobustEnsembleNode ready: {model_name}  v{model_version}  "
            f"base_learners={list(entry_base.keys())}  "
            f"regime_model={'yes' if regime_loaded else 'no'}  "
            f"drift_features={len(self._drift_stats)}"
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_metadata(cls, metadata_path: str | Path) -> "RobustEnsembleNode":
        """Load node from its metadata JSON.  Cached: safe to call repeatedly."""
        metadata_path = Path(metadata_path)
        tag = metadata_path.stem.replace("metadata_", "")
        if tag in cls._cache:
            log.debug(f"RobustEnsembleNode: cache hit for {tag}")
            return cls._cache[tag]

        with open(metadata_path) as f:
            meta = json.load(f)

        paths    = meta.get("file_paths", {})
        base_dir = metadata_path.parent

        # Support both .joblib (v3) and .pkl (v2 backward compat)
        def _resolve(key: str, base_name: str) -> Path:
            p = Path(paths.get(key, ""))
            if str(p) and p.exists():
                return p
            # Try .joblib then .pkl
            for ext in (".joblib", ".pkl"):
                candidate = base_dir / f"{base_name}{ext}"
                if candidate.exists():
                    return candidate
            return base_dir / f"{base_name}.joblib"   # will raise on load if absent

        log.info(f"Loading RobustEnsembleNode [{tag}] …")

        entry_base   = _load(_resolve("entry_base",   f"entry_base_{tag}"))
        entry_meta_m = _load(_resolve("entry_meta",   f"entry_meta_{tag}"))
        exit_base    = _load(_resolve("exit_base",    f"exit_base_{tag}"))
        exit_meta_m  = _load(_resolve("exit_meta",    f"exit_meta_{tag}"))

        try:
            entry_scaler = _load(_resolve("entry_scaler", f"entry_scaler_{tag}"))
        except (FileNotFoundError, OSError):
            entry_scaler = None
        try:
            exit_scaler = _load(_resolve("exit_scaler", f"exit_scaler_{tag}"))
        except (FileNotFoundError, OSError):
            exit_scaler = None

        # Optional: feature drift stats
        drift_stats: Dict[str, Dict] = {}
        drift_path = base_dir / f"feature_drift_{tag}.json"
        if drift_path.exists():
            try:
                with open(drift_path) as f:
                    drift_stats = json.load(f).get("features", {})
                log.info(f"  Loaded drift stats for {len(drift_stats)} features.")
            except Exception as exc:
                log.warning(f"  Could not load drift stats: {exc}")

        # Optional: regime classifier
        regime_clf = None
        regime_meta_path = base_dir / f"regime_metadata_{tag}.json"
        if regime_meta_path.exists():
            try:
                from agent.models.regime_classifier import RegimeClassifier
                regime_clf = RegimeClassifier.from_metadata(regime_meta_path)
                log.info(f"  Regime classifier loaded for [{tag}].")
            except Exception as exc:
                log.warning(f"  Regime classifier not loaded: {exc}")

        node = cls(
            model_name       = meta.get("model_name", f"robust_ensemble_{tag}"),
            model_version    = meta.get("version", "3.0.0"),
            entry_base       = entry_base,
            entry_meta       = entry_meta_m,
            entry_scaler     = entry_scaler,
            exit_base        = exit_base,
            exit_meta        = exit_meta_m,
            exit_scaler      = exit_scaler,
            metadata         = meta,
            drift_stats      = drift_stats,
            regime_classifier= regime_clf,
        )
        cls._cache[tag] = node
        return node

    # ── Internal inference ────────────────────────────────────────────────────

    def _validate_input(self, features: List[float]) -> None:
        if len(features) != len(self._feature_names):
            raise ValueError(
                f"[{self.model_name}] Feature count mismatch: "
                f"expected {len(self._feature_names)}, got {len(features)}"
            )

    def _stack(self, base: Dict[str, Any], meta: Any, X: np.ndarray) -> np.ndarray:
        parts = [m.predict_proba(X) for m in base.values()]
        return meta.predict_proba(np.hstack(parts))

    def _build_exit_vector(
        self,
        features: List[float],
        pos_ctx:    Optional[PositionContext],
        reg_ctx:    Optional[RegimeContext],
    ) -> np.ndarray:
        p = pos_ctx or PositionContext()
        r = reg_ctx or RegimeContext()
        extra = [
            p.unrealised_pnl_pct, p.time_in_trade_ratio,
            p.drawdown_from_peak, p.entry_distance_atr,
            r.adx_14, r.atr_pct_rank, r.vol_zscore,
        ]
        return np.array([features + extra], dtype=np.float32)

    def _predict_entry_proba(
        self,
        X: np.ndarray,
        regime_features: Optional[List[float]] = None,
    ) -> Tuple[np.ndarray, str]:
        """Predict entry probabilities.

        If a RegimeClassifier is loaded AND regime_features are provided,
        use regime-specific entry model.  Otherwise use base stacking ensemble.

        Returns (proba_array_shape_3, regime_name_str).
        """
        if self._regime_clf is not None and regime_features is not None:
            try:
                regime_id   = self._regime_clf.predict_regime(regime_features)
                regime_name = self._regime_clf.get_regime_name(regime_id)
                proba       = self._regime_clf.predict_entry(
                    X[0].tolist(), regime_id
                )
                return proba, regime_name
            except Exception as exc:
                log.warning(
                    f"[{self.model_name}] Regime model failed, "
                    f"falling back to base ensemble: {exc}"
                )

        # Fallback: base stacking ensemble
        proba = self._stack(self._entry_base, self._entry_meta, X)[0]
        return proba, "UNKNOWN"

    # ── MCP interface ─────────────────────────────────────────────────────────

    def predict(self, request: MCPModelRequest) -> MCPModelPrediction:
        """Run entry + exit ensembles in a single call.

        request.context keys (all optional)
        ------------------------------------
        feature_names       List[str]
        position_context    dict  – see PositionContext fields
        regime_context      dict  – see RegimeContext  fields
        regime_features     List[float]  – 7 regime-specific features for RegimeClassifier
        """
        t0 = time.perf_counter()
        self._call_count += 1
        ctx = request.context or {}

        try:
            self._validate_input(request.features)
            features: List[float] = list(request.features)
            X = np.array([features], dtype=np.float32)

            # Resolve contexts
            raw_pos = ctx.get("position_context", {})
            raw_reg = ctx.get("regime_context", {})
            pos_ctx = (
                raw_pos if isinstance(raw_pos, PositionContext)
                else PositionContext(
                    unrealised_pnl_pct   = float(raw_pos.get("unrealised_pnl_pct",   0.0)),
                    time_in_trade_ratio  = float(raw_pos.get("time_in_trade_ratio",  0.0)),
                    drawdown_from_peak   = float(raw_pos.get("drawdown_from_peak",   0.0)),
                    entry_distance_atr   = float(raw_pos.get("entry_distance_atr",   0.0)),
                )
            )
            reg_ctx = (
                raw_reg if isinstance(raw_reg, RegimeContext)
                else RegimeContext(
                    adx_14       = float(raw_reg.get("adx_14",       25.0)),
                    atr_pct_rank = float(raw_reg.get("atr_pct_rank",  0.5)),
                    vol_zscore   = float(raw_reg.get("vol_zscore",    0.0)),
                )
            )

            # Optional raw regime features for RegimeClassifier routing
            regime_features: Optional[List[float]] = ctx.get("regime_features")

            Xe = self._build_exit_vector(features, pos_ctx, reg_ctx)

            # Feature drift check
            drift_warnings: List[str] = []
            if self._drift_stats:
                drift_warnings = _check_drift(
                    features, self._feature_names, self._drift_stats
                )
                if drift_warnings:
                    log.warning(
                        f"[{self.model_name}] Feature drift detected: "
                        f"{drift_warnings[:5]}"
                    )

            # Entry inference (regime-routed or base ensemble)
            entry_proba, regime_name = self._predict_entry_proba(X, regime_features)
            regime_proba: Optional[np.ndarray] = None
            if self._regime_clf is not None and regime_features is not None:
                try:
                    regime_proba = self._regime_clf.predict_regime_proba(regime_features)
                except Exception:
                    pass

            # Exit inference
            exit_proba = self._stack(self._exit_base, self._exit_meta, Xe)[0]

            entry_sig, entry_conf = _entry_signal(entry_proba)
            exit_sig,  exit_conf  = _exit_signal(exit_proba)

            feat_names: List[str] = ctx.get("feature_names") or self._feature_names

            reasoning = _build_reasoning(
                feat_names, features, self._entry_importance,
                entry_sig, entry_conf, exit_sig, exit_conf,
                regime_name=regime_name,
                drift_warnings=drift_warnings,
            )

            t_ms = (time.perf_counter() - t0) * 1000
            self._total_ms += t_ms

            regime_ctx: Dict[str, Any] = {
                "regime_name": regime_name,
            }
            if regime_proba is not None:
                regime_ctx["regime_proba"] = {
                    "range":    round(float(regime_proba[0]), 4),
                    "trend":    round(float(regime_proba[1]), 4),
                    "high_vol": round(float(regime_proba[2]), 4),
                }

            return MCPModelPrediction(
                model_name          = self.model_name,
                model_version       = self.model_version,
                prediction          = entry_sig,
                confidence          = entry_conf,
                reasoning           = reasoning,
                features_used       = feat_names,
                feature_importance  = self._entry_importance,
                computation_time_ms = round(t_ms, 2),
                health_status       = self._health_status,
                context = {
                    "entry_signal":     entry_sig,
                    "entry_confidence": entry_conf,
                    "entry_proba": {
                        "sell": round(float(entry_proba[0]), 4),
                        "hold": round(float(entry_proba[1]), 4),
                        "buy":  round(float(entry_proba[2]), 4),
                    },
                    "exit_signal":     exit_sig,
                    "exit_confidence": exit_conf,
                    "exit_proba": {
                        "hold": round(float(exit_proba[0]), 4),
                        "exit": round(float(exit_proba[1]), 4),
                    },
                    "regime":          regime_ctx,
                    "drift_warnings":  drift_warnings,
                    "position_context_used": {
                        "unrealised_pnl_pct":  pos_ctx.unrealised_pnl_pct,
                        "time_in_trade_ratio": pos_ctx.time_in_trade_ratio,
                        "drawdown_from_peak":  pos_ctx.drawdown_from_peak,
                        "entry_distance_atr":  pos_ctx.entry_distance_atr,
                    },
                    "regime_context_used": {
                        "adx_14":       reg_ctx.adx_14,
                        "atr_pct_rank": reg_ctx.atr_pct_rank,
                        "vol_zscore":   reg_ctx.vol_zscore,
                    },
                },
            )

        except Exception as exc:
            self._error_count += 1
            if self._error_count >= 5:
                self._health_status = "degraded"
            t_ms = (time.perf_counter() - t0) * 1000
            log.error(f"[{self.model_name}] Inference error: {exc}", exc_info=True)
            return MCPModelPrediction(
                model_name          = self.model_name,
                model_version       = self.model_version,
                prediction          = 0.0,
                confidence          = 0.0,
                reasoning           = f"Inference failed: {exc}",
                features_used       = [],
                feature_importance  = {},
                computation_time_ms = round(t_ms, 2),
                health_status       = "error",
            )

    # ── Health endpoint ───────────────────────────────────────────────────────

    def get_health(self) -> Dict[str, Any]:
        avg_ms = (self._total_ms / self._call_count) if self._call_count else 0.0
        return {
            "status":              self._health_status,
            "model_name":          self.model_name,
            "version":             self.model_version,
            "call_count":          self._call_count,
            "error_count":         self._error_count,
            "avg_inference_ms":    round(avg_ms, 2),
            "base_learners":       list(self._entry_base.keys()),
            "feature_count":       len(self._feature_names),
            "exit_feature_count":  len(self._exit_feature_names),
            "drift_features_monitored": len(self._drift_stats),
            "regime_model_loaded": self._regime_clf is not None,
            "training_metrics": {
                "entry": self._metadata.get("entry_test_metrics", {}),
                "exit":  self._metadata.get("exit_test_metrics",  {}),
            },
            "sharpe_proxy":     self._metadata.get("sharpe_proxy", None),
            "dataset_sha256":   self._metadata.get("dataset_sha256", None),
            "signal_thresholds": {
                "entry": ENTRY_THRESHOLD,
                "exit":  EXIT_THRESHOLD,
            },
        }

    def get_model_info(self) -> Dict[str, Any]:
        return {
            "model_name":       self.model_name,
            "model_version":    self.model_version,
            "model_type":       "stacking_ensemble_v3",
            "features_required": self._feature_names,
            "feature_count":    len(self._feature_names),
            "output": {
                "prediction":             "entry signal [-1, +1]",
                "context.exit_signal":    "exit signal  [-1, +1]",
                "context.entry_confidence": "[0, 1]",
                "context.exit_confidence":  "[0, 1]",
                "context.regime":           "regime name + proba",
                "context.drift_warnings":   "list of drifted feature names",
            },
            "base_learners": list(self._entry_base.keys()),
        }

    def is_healthy(self) -> bool:
        return self._health_status in ("healthy", "degraded")

    def warm_up(self, n_calls: int = 3) -> None:
        """Perform n_calls synthetic inferences to JIT-compile tree paths."""
        rng = np.random.default_rng(0)
        for _ in range(n_calls):
            dummy = rng.uniform(-1.0, 1.0, size=len(self._feature_names)).tolist()
            from agent.models.mcp_model_node import MCPModelRequest as _Req
            req = _Req(features=dummy, context={})
            self.predict(req)
        self._call_count = 0
        self._total_ms   = 0.0
        log.info(f"[{self.model_name}] Warm-up complete ({n_calls} passes).")
