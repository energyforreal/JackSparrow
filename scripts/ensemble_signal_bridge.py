"""
ensemble_signal_bridge.py  (v3)
--------------------------------
JackSparrow – Ensemble Signal Bridge

Changes from v2 (audit-driven)
--------------------------------
  [NEW]  Dynamic timeframe weight adaptation based on detected market regime
         (TREND → higher-TF weights, RANGE/HIGH_VOL → lower-TF weights)
  [NEW]  Signal thresholds imported from train_robust_ensemble (single source of truth)
  [NEW]  Regime-aware weight selection applied per predict() cycle
  [NEW]  regime_features passed through to node for RegimeClassifier routing
  [FIX]  All v2 improvements retained

Multi-timeframe default weights (static fallback, no regime model)
---------------------------------------------------------------------------
  4h  → 40 %  (macro trend)
  2h  → 20 %  (swing context)
  1h  → 20 %  (intraday trend)
  30m → 12 %  (momentum)
  15m →  8 %  (noise filter)

Dynamic regime-aware weights
----------------------------
  TREND    : 4h=40%  2h=30%  1h=20%  30m=7%  15m=3%   (macro dominant)
  RANGE    : 4h=10%  2h=15%  1h=20%  30m=25% 15m=30%  (micro dominant)
  HIGH_VOL : 4h=15%  2h=20%  1h=25%  30m=25% 15m=15%  (balanced)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from agent.data.feature_list import FEATURE_LIST
from agent.models.mcp_model_node import MCPModelRequest
from agent.models.robust_ensemble_node import (
    ENTRY_THRESHOLD,
    EXIT_THRESHOLD,
    PositionContext,
    RegimeContext,
    RobustEnsembleNode,
)

log = logging.getLogger(__name__)

# Regime ids (must match regime_classifier.py constants)
_REGIME_RANGE    = 0
_REGIME_TREND    = 1
_REGIME_HIGH_VOL = 2

# ─────────────────────────────────────────────────────────────────────────────
# Regime-driven timeframe weight tables
# ─────────────────────────────────────────────────────────────────────────────

REGIME_TF_WEIGHTS: Dict[int, Dict[str, float]] = {
    _REGIME_TREND: {
        "4h": 0.40, "2h": 0.30, "1h": 0.20, "30m": 0.07, "15m": 0.03,
    },
    _REGIME_RANGE: {
        "4h": 0.10, "2h": 0.15, "1h": 0.20, "30m": 0.25, "15m": 0.30,
    },
    _REGIME_HIGH_VOL: {
        "4h": 0.15, "2h": 0.20, "1h": 0.25, "30m": 0.25, "15m": 0.15,
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Output dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EntrySignal:
    signal:        float
    confidence:    float
    direction:     str        # "BUY" | "HOLD" | "SELL"
    should_enter:  bool
    proba:         Dict[str, Any] = field(default_factory=dict)
    reasoning:     str  = ""
    model_name:    str  = ""
    timeframe:     str  = ""
    regime:        str  = "UNKNOWN"   # NEW

    @property
    def signal_strength(self) -> str:
        a = abs(self.signal)
        if a >= 0.70: return "STRONG"
        if a >= 0.40: return "MODERATE"
        if a >= 0.15: return "WEAK"
        return "NEUTRAL"


@dataclass
class ExitSignal:
    signal:       float
    confidence:   float
    should_exit:  bool
    proba:        Dict[str, Any] = field(default_factory=dict)
    reasoning:    str  = ""
    model_name:   str  = ""
    timeframe:    str  = ""

    @property
    def urgency(self) -> str:
        if self.signal >= 0.70: return "URGENT"
        if self.signal >= 0.40: return "HIGH"
        if self.signal >= 0.10: return "MODERATE"
        return "LOW"


@dataclass
class CombinedSignal:
    entry:              EntrySignal
    exit:               ExitSignal
    consensus:          str
    overall_confidence: float
    regime:             str  = "UNKNOWN"    # NEW – dominant regime across TFs
    drift_warnings:     List[str] = field(default_factory=list)  # NEW


CONSENSUS_LABELS = frozenset({
    "ENTER_LONG", "ENTER_SHORT", "EXIT", "HOLD", "WAIT",
})


# ─────────────────────────────────────────────────────────────────────────────
# Bridge
# ─────────────────────────────────────────────────────────────────────────────

class EnsembleSignalBridge:
    """Multi-timeframe bridge over one or more RobustEnsembleNodes (v3).

    Key upgrades over v2
    --------------------
    • Dynamic timeframe weight adaptation: weights shift based on detected regime.
      TREND → higher TFs; RANGE/HIGH_VOL → lower TFs.
    • regime_features forwarded to each node so the RegimeClassifier can route
      to the correct entry model.
    • Signal thresholds unified with the training script constants.
    """

    DEFAULT_TF_WEIGHTS: Dict[str, float] = {
        "4h":  0.40,
        "2h":  0.20,
        "1h":  0.20,
        "30m": 0.12,
        "15m": 0.08,
    }

    # Use centralised constants as class attributes
    ENTRY_THRESHOLD: float = ENTRY_THRESHOLD
    EXIT_THRESHOLD:  float = EXIT_THRESHOLD

    def __init__(
        self,
        nodes:           Dict[str, RobustEnsembleNode],
        tf_weights:      Optional[Dict[str, float]] = None,
        entry_threshold: float = ENTRY_THRESHOLD,
        exit_threshold:  float = EXIT_THRESHOLD,
        dynamic_weights: bool  = True,
        quality_filter:  Optional[Callable[[CombinedSignal], Optional[CombinedSignal]]] = None,
    ) -> None:
        if not nodes:
            raise ValueError("At least one RobustEnsembleNode is required.")

        self._nodes           = nodes
        self._entry_threshold = entry_threshold
        self._exit_threshold  = exit_threshold
        self._dynamic_weights = dynamic_weights
        self._quality_filter  = quality_filter
        self._static_tf_weights = tf_weights or self.DEFAULT_TF_WEIGHTS

        # Normalised static weights (used when dynamic_weights=False or no regime)
        self._weights: Dict[str, float] = self._normalise_weights(
            self._static_tf_weights, nodes
        )

        log.info(
            f"EnsembleSignalBridge ready  "
            f"timeframes={sorted(nodes.keys())}  "
            f"static_weights={self._weights}  "
            f"dynamic_weights={dynamic_weights}"
        )

    @staticmethod
    def _normalise_weights(
        raw: Dict[str, float],
        nodes: Dict[str, RobustEnsembleNode],
    ) -> Dict[str, float]:
        w = {tf: raw.get(tf, 0.20) for tf in nodes}
        total = sum(w.values()) or 1.0
        return {tf: v / total for tf, v in w.items()}

    def _weights_for_regime(self, regime_id: Optional[int]) -> Dict[str, float]:
        """Return normalised weights for the given regime id."""
        if regime_id is None or not self._dynamic_weights:
            return self._weights
        regime_table = REGIME_TF_WEIGHTS.get(regime_id, self._static_tf_weights)
        return self._normalise_weights(regime_table, self._nodes)

    # ── Factory helpers ───────────────────────────────────────────────────────

    @classmethod
    def from_registry(
        cls,
        registry: Any,
        symbol: str = "BTCUSD",
        timeframes: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> "EnsembleSignalBridge":
        tfs   = timeframes or ["15m", "30m", "1h", "2h", "4h"]
        nodes: Dict[str, RobustEnsembleNode] = {}
        for tf in tfs:
            name = f"robust_ensemble_{symbol}_{tf}"
            try:
                node = registry.get_node(name)
                if isinstance(node, RobustEnsembleNode):
                    nodes[tf] = node
                else:
                    log.warning(f"Registry node '{name}' is not a RobustEnsembleNode.")
            except Exception as exc:
                log.warning(f"Could not load '{name}' from registry: {exc}")
        if not nodes:
            raise RuntimeError(f"No RobustEnsembleNode found in registry for {symbol}.")
        return cls(nodes, **kwargs)

    @classmethod
    def from_metadata_files(
        cls,
        metadata_paths: List[str],
        **kwargs: Any,
    ) -> "EnsembleSignalBridge":
        from pathlib import Path
        nodes: Dict[str, RobustEnsembleNode] = {}
        for path in metadata_paths:
            node = RobustEnsembleNode.from_metadata(path)
            tf   = node.model_name.rsplit("_", 1)[-1]
            nodes[tf] = node
        return cls(nodes, **kwargs)

    # ── Core ──────────────────────────────────────────────────────────────────

    def _make_request(
        self,
        features:       List[float],
        feature_names:  Optional[List[str]],
        pos_ctx:        Optional[PositionContext],
        reg_ctx:        Optional[RegimeContext],
        regime_features: Optional[List[float]] = None,
    ) -> MCPModelRequest:
        ctx: Dict[str, Any] = {
            "feature_names": feature_names or FEATURE_LIST,
        }
        if pos_ctx:
            ctx["position_context"] = {
                "unrealised_pnl_pct":  pos_ctx.unrealised_pnl_pct,
                "time_in_trade_ratio": pos_ctx.time_in_trade_ratio,
                "drawdown_from_peak":  pos_ctx.drawdown_from_peak,
                "entry_distance_atr":  pos_ctx.entry_distance_atr,
            }
        if reg_ctx:
            ctx["regime_context"] = {
                "adx_14":       reg_ctx.adx_14,
                "atr_pct_rank": reg_ctx.atr_pct_rank,
                "vol_zscore":   reg_ctx.vol_zscore,
            }
        if regime_features is not None:
            ctx["regime_features"] = regime_features   # for RegimeClassifier routing
        return MCPModelRequest(features=features, context=ctx)

    def _detect_dominant_regime(
        self,
        per_tf_contexts: Dict[str, Dict],
    ) -> Optional[int]:
        """Extract the majority regime id from per-TF predictions."""
        regime_votes: Dict[int, float] = {}
        for tf, ctx in per_tf_contexts.items():
            regime_info = ctx.get("regime", {})
            rproba = regime_info.get("regime_proba")
            if rproba is None:
                continue
            # Vote weighted by prediction confidence
            for rid, name in [(_REGIME_RANGE, "range"), (_REGIME_TREND, "trend"), (_REGIME_HIGH_VOL, "high_vol")]:
                p = float(rproba.get(name, 0.0))
                regime_votes[rid] = regime_votes.get(rid, 0.0) + p
        if not regime_votes:
            return None
        return max(regime_votes, key=lambda r: regime_votes[r])

    def get_combined_signal(
        self,
        features:        List[float],
        pos_ctx:         Optional[PositionContext] = None,
        reg_ctx:         Optional[RegimeContext]   = None,
        feature_names:   Optional[List[str]]       = None,
        timeframe:       Optional[str]             = None,
        regime_features: Optional[List[float]]     = None,
    ) -> CombinedSignal:
        """Return entry + exit signals from a single predict() pass per node.

        Dynamic weight adaptation
        --------------------------
        If regime model artifacts are loaded AND regime_features are provided,
        the bridge first collects regime probabilities from each node, then
        re-weights timeframes according to the dominant detected regime.
        """
        request = self._make_request(
            features, feature_names, pos_ctx, reg_ctx, regime_features
        )
        nodes = (
            {timeframe: self._nodes[timeframe]}
            if timeframe and timeframe in self._nodes
            else self._nodes
        )

        # ── First pass: collect per-TF predictions ────────────────────────────
        per_tf_preds: Dict[str, Any] = {}
        per_tf_ctx:   Dict[str, Dict] = {}
        for tf, node in nodes.items():
            pred = node._predict_sync(request)
            per_tf_preds[tf] = pred
            per_tf_ctx[tf]   = pred.context or {}

        # ── Detect dominant regime, select weights ────────────────────────────
        dominant_regime_id = self._detect_dominant_regime(per_tf_ctx)
        weights = self._weights_for_regime(dominant_regime_id)

        regime_names_map = {
            _REGIME_RANGE: "RANGE",
            _REGIME_TREND: "TREND",
            _REGIME_HIGH_VOL: "HIGH_VOL",
        }
        dominant_regime_name = (
            regime_names_map.get(dominant_regime_id, "UNKNOWN")
            if dominant_regime_id is not None else "UNKNOWN"
        )

        # ── Aggregate signals ─────────────────────────────────────────────────
        e_sigs: List[Tuple[float, float, float]] = []
        x_sigs: List[Tuple[float, float, float]] = []
        e_probas: Dict[str, Dict] = {}
        x_probas: Dict[str, Dict] = {}
        reasoning_parts: List[str] = []
        all_drift_warnings: List[str] = []

        for tf, pred in per_tf_preds.items():
            w   = weights.get(tf, 1.0 / len(nodes))
            ctx = per_tf_ctx[tf]

            e_sig  = float(ctx.get("entry_signal", pred.prediction))
            e_conf = float(ctx.get("entry_confidence", pred.confidence))
            x_sig  = float(ctx.get("exit_signal", 0.0))
            x_conf = float(ctx.get("exit_confidence", 0.0))

            e_sigs.append((e_sig, e_conf, w))
            x_sigs.append((x_sig, x_conf, w))
            e_probas[tf] = ctx.get("entry_proba", {})
            x_probas[tf] = ctx.get("exit_proba",  {})
            all_drift_warnings.extend(ctx.get("drift_warnings", []))
            reasoning_parts.append(
                f"[{tf} w={w:.2f} r={ctx.get('regime', {}).get('regime_name', '?')}] "
                f"entry={e_sig:+.3f} exit={x_sig:+.3f}"
            )

        e_signal = sum(s * w for s, _, w in e_sigs)
        e_conf   = sum(c * w for _, c, w in e_sigs)
        x_signal = sum(s * w for s, _, w in x_sigs)
        x_conf   = sum(c * w for _, c, w in x_sigs)

        direction = self._direction(e_signal)
        entry = EntrySignal(
            signal       = round(e_signal, 4),
            confidence   = round(e_conf, 4),
            direction    = direction,
            should_enter = abs(e_signal) >= self._entry_threshold and direction != "HOLD",
            proba        = e_probas,
            reasoning    = f"Multi-TF[{dominant_regime_name}]: " + "  |  ".join(reasoning_parts),
            model_name   = "robust_ensemble_multi_tf_v3",
            regime       = dominant_regime_name,
        )
        exit_ = ExitSignal(
            signal      = round(x_signal, 4),
            confidence  = round(x_conf, 4),
            should_exit = x_signal >= self._exit_threshold,
            proba       = x_probas,
            reasoning   = "Multi-TF exit: " + "  |  ".join(reasoning_parts),
            model_name  = "robust_ensemble_exit_multi_tf_v3",
        )

        # Deduplicate drift warnings
        unique_drifts = list(dict.fromkeys(all_drift_warnings))

        consensus = self._consensus(entry, exit_)
        combined = CombinedSignal(
            entry              = entry,
            exit               = exit_,
            consensus          = consensus,
            overall_confidence = round(0.6 * e_conf + 0.4 * x_conf, 4),
            regime             = dominant_regime_name,
            drift_warnings     = unique_drifts,
        )
        # Optional trade-quality filter: downgrade or reject signal
        if self._quality_filter is not None:
            try:
                filtered = self._quality_filter(combined)
                if filtered is not None:
                    return filtered
                # Filter rejected: return same signal but force WAIT
                return CombinedSignal(
                    entry=combined.entry,
                    exit=combined.exit,
                    consensus="WAIT",
                    overall_confidence=combined.overall_confidence,
                    regime=combined.regime,
                    drift_warnings=combined.drift_warnings,
                )
            except Exception as e:
                log.warning("Quality filter failed: %s", e)
        return combined

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def get_entry_signal(
        self,
        features:        List[float],
        feature_names:   Optional[List[str]] = None,
        timeframe:       Optional[str]       = None,
        reg_ctx:         Optional[RegimeContext] = None,
        regime_features: Optional[List[float]] = None,
    ) -> EntrySignal:
        return self.get_combined_signal(
            features, feature_names=feature_names,
            timeframe=timeframe, reg_ctx=reg_ctx,
            regime_features=regime_features,
        ).entry

    def get_exit_signal(
        self,
        features:        List[float],
        pos_ctx:         Optional[PositionContext] = None,
        reg_ctx:         Optional[RegimeContext]   = None,
        feature_names:   Optional[List[str]]       = None,
        timeframe:       Optional[str]             = None,
        regime_features: Optional[List[float]]     = None,
    ) -> ExitSignal:
        return self.get_combined_signal(
            features, pos_ctx=pos_ctx, reg_ctx=reg_ctx,
            feature_names=feature_names, timeframe=timeframe,
            regime_features=regime_features,
        ).exit

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _direction(self, signal: float) -> str:
        if signal >  self._entry_threshold: return "BUY"
        if signal < -self._entry_threshold: return "SELL"
        return "HOLD"

    @staticmethod
    def _consensus(entry: EntrySignal, exit_: ExitSignal) -> str:
        if exit_.should_exit:
            return "EXIT"
        if entry.direction == "BUY"  and entry.should_enter: return "ENTER_LONG"
        if entry.direction == "SELL" and entry.should_enter: return "ENTER_SHORT"
        if entry.direction == "HOLD":                        return "HOLD"
        return "WAIT"

    def warm_up_all(self, n_calls: int = 3) -> None:
        for tf, node in self._nodes.items():
            log.info(f"  Warming up [{tf}] …")
            node.warm_up(n_calls)
        log.info(f"EnsembleSignalBridge: all {len(self._nodes)} nodes warmed up.")

    def health_report(self) -> Dict[str, Any]:
        report: Dict[str, Any] = {}
        for tf, node in self._nodes.items():
            h = node.get_health()
            report[tf] = {
                "status":                    h["status"],
                "model_name":                h["model_name"],
                "version":                   h["version"],
                "call_count":                h["call_count"],
                "error_count":               h["error_count"],
                "avg_inference_ms":          h["avg_inference_ms"],
                "base_learners":             h["base_learners"],
                "regime_model_loaded":       h.get("regime_model_loaded", False),
                "drift_features_monitored":  h.get("drift_features_monitored", 0),
                "sharpe_proxy":              h.get("sharpe_proxy"),
                "dataset_sha256":            h.get("dataset_sha256"),
                "training_metrics":          h.get("training_metrics", {}),
                "signal_thresholds":         h.get("signal_thresholds", {}),
            }
        report["_weights"]        = self._weights
        report["_dynamic_weights"] = self._dynamic_weights
        return report

    def __repr__(self) -> str:
        return (
            f"EnsembleSignalBridge("
            f"timeframes={sorted(self._nodes.keys())}, "
            f"weights={self._weights}, "
            f"dynamic={self._dynamic_weights})"
        )


# ── Re-exports ───────────────────────────────────────────────────────────────
__all__ = [
    "EnsembleSignalBridge",
    "PositionContext",
    "RegimeContext",
    "EntrySignal",
    "ExitSignal",
    "CombinedSignal",
    "REGIME_TF_WEIGHTS",
]
