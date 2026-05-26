"""
Scenario Runner — replicates the full MCP orchestrator pipeline
with synthetic injected market frames (no exchange connection required).

Pipeline executed in order:
  1. v43 model inference   (JackSparrowV43Node.predict)
  2. Multi-horizon evidence (build_multi_horizon_evidence)
  3. Market structure       (classify_market_structure)
  4. Thesis engine          (agent_thesis_engine.evaluate)
  5. Gate application       (apply_gates_to_ml_validation)
  6. Trade scorer           (score_trade_setup)
  7. Policy engine          (agent_policy_engine.evaluate)
  8. Portfolio guard        (evaluate_portfolio_guard)

Each layer's output is captured verbatim and returned in a ScenarioTrace.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import structlog

logger = structlog.get_logger()

# ── default model path ─────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_META = (
    _REPO_ROOT
    / "agent/model_storage/JackSparrow_v43_models_BTCUSD/metadata_v43.json"
)


# ──────────────────────────────────────────────────────────────────────────
# Trace dataclass
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class LayerTrace:
    name: str
    ok: bool
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class ScenarioTrace:
    scenario_name: str
    description: str
    symbol: str
    expected: Dict[str, Any]
    layers: List[LayerTrace] = field(default_factory=list)
    assertions: Dict[str, Any] = field(default_factory=dict)  # filled by assertions module
    total_ms: float = 0.0
    error: Optional[str] = None

    # ── convenience accessors ──────────────────────────────────────────────
    def layer(self, name: str) -> Optional[LayerTrace]:
        for lyr in self.layers:
            if lyr.name == name:
                return lyr
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario": self.scenario_name,
            "description": self.description,
            "symbol": self.symbol,
            "total_ms": round(self.total_ms, 1),
            "error": self.error,
            "layers": [
                {
                    "name": lyr.name,
                    "ok": lyr.ok,
                    "duration_ms": round(lyr.duration_ms, 1),
                    "error": lyr.error,
                    **lyr.output,
                }
                for lyr in self.layers
            ],
            "expected": self.expected,
            "assertions": self.assertions,
        }


# ──────────────────────────────────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────────────────────────────────

class ScenarioRunner:
    """
    Loads the v43 model once, then runs any number of scenarios through the
    full pipeline without touching the exchange.
    """

    def __init__(
        self,
        metadata_path: Optional[Path] = None,
        symbol: str = "BTCUSD",
    ) -> None:
        self.metadata_path = Path(metadata_path or _DEFAULT_META)
        self.symbol = symbol
        self._node: Any = None   # JackSparrowV43Node — loaded on first use

    # ── lazy model load ────────────────────────────────────────────────────

    def _load_model(self) -> None:
        if self._node is not None:
            return
        from agent.models.jack_sparrow_v43_node import JackSparrowV43Node
        self._node = JackSparrowV43Node.from_metadata_path(self.metadata_path)
        logger.info(
            "scenario_runner_model_loaded",
            path=str(self.metadata_path),
            forward_bars=self._node.training_forward_bars,
        )

    # ── helper: time a coroutine or sync call ──────────────────────────────

    @staticmethod
    async def _timed_async(coro) -> tuple[Any, float]:
        t0 = time.perf_counter()
        result = await coro
        return result, (time.perf_counter() - t0) * 1000.0

    @staticmethod
    def _timed_sync(fn, *args, **kwargs) -> tuple[Any, float]:
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        return result, (time.perf_counter() - t0) * 1000.0

    # ──────────────────────────────────────────────────────────────────────
    # Public: run one scenario
    # ──────────────────────────────────────────────────────────────────────

    async def run(self, scenario: Dict[str, Any]) -> ScenarioTrace:
        t_total = time.perf_counter()
        self._load_model()

        trace = ScenarioTrace(
            scenario_name=scenario["scenario_name"],
            description=scenario.get("description", ""),
            symbol=self.symbol,
            expected=scenario.get("expected", {}),
        )

        frames: Dict[str, Any] = scenario.get("frames", {})
        portfolio_state: Dict[str, Any] = scenario.get("portfolio_state", {})

        try:
            # ── 1. ML inference ───────────────────────────────────────────
            ml_lyr = await self._run_ml_inference(frames)
            trace.layers.append(ml_lyr)
            if not ml_lyr.ok:
                trace.error = ml_lyr.error
                return trace

            pred_ctx: Dict[str, Any] = ml_lyr.output["pred_context"]
            closed_feats: Dict[str, Any] = dict(pred_ctx.get("closed_bar_features") or {})
            overrides = scenario.get("feature_overrides")
            if isinstance(overrides, dict):
                for k, v in overrides.items():
                    try:
                        closed_feats[str(k)] = float(v)
                    except (TypeError, ValueError):
                        continue
                pred_ctx["closed_bar_features"] = closed_feats

            # ── 2. Multi-horizon evidence ─────────────────────────────────
            mh_lyr = self._run_multi_horizon(pred_ctx)
            trace.layers.append(mh_lyr)
            mh_evidence = mh_lyr.output.get("_obj")   # live object for gate calls
            gate_head = mh_lyr.output.get("_gate_head")
            if not mh_lyr.ok or mh_evidence is None:
                trace.error = mh_lyr.error or "multi_horizon_failed"
                return trace

            # ── 3. Market structure ───────────────────────────────────────
            struct_lyr = self._run_market_structure(pred_ctx)
            trace.layers.append(struct_lyr)
            structure = struct_lyr.output.get("_obj")

            # ── 4. Thesis engine ──────────────────────────────────────────
            regime = str(
                scenario.get("force_regime")
                or gate_head.regime
                or pred_ctx.get("regime", "neutral")
                or "neutral"
            )
            thesis_lyr = self._run_thesis(
                regime,
                closed_feats,
                frames,
                portfolio_state,
                scenario=scenario,
                structure=structure,
            )
            trace.layers.append(thesis_lyr)
            thesis_verdict = thesis_lyr.output.get("_obj")
            strategy_candidate = thesis_lyr.output.get("_strategy")

            # ── 5. Gate application ───────────────────────────────────────
            gate_lyr = self._run_gates(
                pred_ctx, gate_head, frames.get("v43_df5m"), scenario=scenario
            )
            trace.layers.append(gate_lyr)
            ml_validation = gate_lyr.output.get("_obj")

            # ── 6. Trade scorer ───────────────────────────────────────────
            score_lyr = self._run_scorer(strategy_candidate, ml_validation, structure)
            trace.layers.append(score_lyr)
            trade_score = score_lyr.output.get("_obj")

            # ── 7. Policy engine ──────────────────────────────────────────
            policy_lyr = self._run_policy(
                pred_ctx, ml_validation, strategy_candidate, trade_score,
                mh_evidence, regime, closed_feats,
            )
            trace.layers.append(policy_lyr)
            policy_verdict = policy_lyr.output.get("_obj")

            # ── 8. Portfolio guard ────────────────────────────────────────
            guard_lyr = self._run_portfolio_guard(
                policy_verdict,
                portfolio_state,
                scenario=scenario,
            )
            trace.layers.append(guard_lyr)
            guard_decision = guard_lyr.output.get("_obj")

            # ── Final decision summary ────────────────────────────────────
            final_signal = policy_verdict.signal if policy_verdict else "UNKNOWN"
            final_size = float(policy_verdict.position_size) if policy_verdict else 0.0
            guard_action = guard_decision.action if guard_decision else "unknown"
            is_entry = final_signal in {"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"}

            trace.layers.append(LayerTrace(
                name="final_decision",
                ok=True,
                output={
                    "signal": final_signal,
                    "execute": is_entry and guard_action != "block",
                    "position_size": final_size,
                    "guard_action": guard_action,
                    "reason": list(policy_verdict.reason_codes) if policy_verdict else [],
                },
            ))

        except Exception as exc:
            trace.error = f"{type(exc).__name__}: {exc}"
            logger.error(
                "scenario_runner_fatal",
                scenario=scenario["scenario_name"],
                error=str(exc),
                tb=traceback.format_exc(),
            )

        trace.total_ms = (time.perf_counter() - t_total) * 1000.0
        return trace

    # ──────────────────────────────────────────────────────────────────────
    # Layer runners
    # ──────────────────────────────────────────────────────────────────────

    async def _run_ml_inference(self, frames: Dict[str, Any]) -> LayerTrace:
        from agent.models.mcp_model_node import MCPModelRequest
        try:
            req = MCPModelRequest(
                request_id=f"scenario_{int(time.time())}",
                features=[],
                context={k: v for k, v in frames.items()},
                require_explanation=True,
            )
            pred, ms = await self._timed_async(self._node.predict(req))
            pctx: Dict[str, Any] = dict(pred.context or {})

            mh = pctx.get("multi_horizon_heads") or {}
            heads_summary = {
                hk: {
                    "expected_return": float((hv or {}).get("expected_return", 0)),
                    "threshold": float((hv or {}).get("threshold", 0)),
                    "direction": "LONG" if float((hv or {}).get("expected_return", 0)) > float((hv or {}).get("threshold", 0)) else "SHORT" if float((hv or {}).get("expected_return", 0)) < -float((hv or {}).get("short_threshold", float((hv or {}).get("threshold", 0)))) else "FLAT",
                }
                for hk, hv in mh.items()
                if isinstance(hv, dict)
            }

            return LayerTrace(
                name="ml_inference",
                ok=pred.health_status not in ("degraded", "error"),
                duration_ms=ms,
                output={
                    "health": pred.health_status,
                    "expected_return": float(pctx.get("expected_return", 0)),
                    "threshold": float(pctx.get("threshold", 0.005)),
                    "short_threshold": float(pctx.get("short_threshold", pctx.get("threshold", 0.005))),
                    "regime": str(pctx.get("regime", "neutral")),
                    "uncertainty": float(pctx.get("uncertainty", 0)),
                    "unc_scale": float(pctx.get("unc_scale", 1.0)),
                    "heads": heads_summary,
                    "pred_context": pctx,  # carried forward (stripped from dict output)
                },
            )
        except Exception as exc:
            return LayerTrace(name="ml_inference", ok=False, error=f"{type(exc).__name__}: {exc}")

    def _run_multi_horizon(self, pred_ctx: Dict[str, Any]) -> LayerTrace:
        from agent.core.multi_horizon_evidence import (
            build_multi_horizon_evidence,
            primary_head_for_gates,
        )
        from feature_store.jacksparrow_v43_multihead import primary_execution_horizon_bars
        from agent.core.config import settings
        try:
            head_payloads = pred_ctx.get("multi_horizon_heads")
            if not isinstance(head_payloads, dict) or not head_payloads:
                return LayerTrace(name="multi_horizon", ok=False, error="multi_horizon_heads missing")

            # resolve bundle metadata from model node
            bm = getattr(self._node, "_bundle_metadata", {})
            short_enabled = bool(getattr(settings, "jacksparrow_v43_short_execution_enabled", False))
            eps = float(getattr(settings, "jacksparrow_v43_near_threshold_epsilon", 0.0) or 0.0)

            mh_evidence, ms = self._timed_sync(
                build_multi_horizon_evidence,
                head_payloads, bm,
                short_enabled=short_enabled,
                eps=eps,
            )
            gate_head = primary_head_for_gates(mh_evidence)

            heads_out = {}
            for k, h in (mh_evidence.heads or {}).items():
                heads_out[k] = {
                    "direction": h.direction,
                    "expected_return": round(float(h.expected_return), 6),
                    "threshold": round(float(h.threshold), 6),
                    "forward_bars": int(h.forward_bars or 0),
                }

            exec_head = mh_evidence.heads.get(mh_evidence.execution_head_key)
            dominant_dir = str(getattr(exec_head, "direction", "FLAT")) if exec_head else "FLAT"

            return LayerTrace(
                name="multi_horizon",
                ok=True,
                duration_ms=ms,
                output={
                    "alignment_score": round(float(mh_evidence.alignment_score), 3),
                    "dominant_direction": dominant_dir,
                    "opposition_detected": mh_evidence.opposition_detected,
                    "primary_head": str(getattr(gate_head, "horizon_key", "?")),
                    "primary_expected_return": round(float(gate_head.expected_return), 6),
                    "primary_threshold": round(float(gate_head.threshold), 6),
                    "heads": heads_out,
                    "_obj": mh_evidence,
                    "_gate_head": gate_head,
                },
            )
        except Exception as exc:
            return LayerTrace(name="multi_horizon", ok=False, error=f"{type(exc).__name__}: {exc}")

    def _run_market_structure(self, pred_ctx: Dict[str, Any]) -> LayerTrace:
        from agent.core.market_structure import classify_market_structure
        try:
            closed_feats = pred_ctx.get("closed_bar_features") or {}
            regime = str(pred_ctx.get("regime", "neutral") or "neutral")
            features_dict = {str(k): float(v) for k, v in closed_feats.items() if v == v}

            structure, ms = self._timed_sync(
                classify_market_structure, features_dict, v43_regime=regime
            )
            return LayerTrace(
                name="market_structure",
                ok=True,
                duration_ms=ms,
                output={
                    "market_type": structure.market_type,
                    "regime": structure.regime,
                    "adx": round(float(structure.adx), 3),
                    "atr_pct": round(float(structure.atr_pct), 5),
                    "vol_regime": round(float(structure.vol_regime), 3),
                    "liquidity_ok": structure.liquidity_ok,
                    "chop_market": structure.chop_market,
                    "reason_codes": structure.reason_codes,
                    "_obj": structure,
                },
            )
        except Exception as exc:
            return LayerTrace(name="market_structure", ok=False, error=f"{type(exc).__name__}: {exc}")

    def _run_thesis(
        self,
        regime: str,
        closed_feats: Dict[str, Any],
        frames: Dict[str, Any],
        portfolio_state: Dict[str, Any],
        *,
        scenario: Optional[Dict[str, Any]] = None,
        structure: Any = None,
    ) -> LayerTrace:
        from agent.core.agent_thesis_engine import agent_thesis_engine
        from agent.core.ml_validator import thesis_verdict_to_strategy_candidate
        try:
            features_dict = {str(k): float(v) for k, v in closed_feats.items() if v == v}
            mc: Dict[str, Any] = {
                "symbol": self.symbol,
                "features": features_dict,
                "regime": regime,
                "v43_regime": regime,
                "has_open_position": False,
            }
            if structure is not None and hasattr(structure, "to_dict"):
                ms_dict = dict(structure.to_dict())
                ms_over = (scenario or {}).get("market_structure_overrides")
                if isinstance(ms_over, dict):
                    ms_dict.update(ms_over)
                mc["market_structure"] = ms_dict
            elif isinstance((scenario or {}).get("market_structure_overrides"), dict):
                mc["market_structure"] = dict(scenario["market_structure_overrides"])
            mc.update({k: v for k, v in portfolio_state.items() if k != "positions"})
            verdict, ms = self._timed_sync(agent_thesis_engine.evaluate, regime, mc)
            strategy = thesis_verdict_to_strategy_candidate(verdict)

            return LayerTrace(
                name="thesis",
                ok=True,
                duration_ms=ms,
                output={
                    "signal": verdict.signal,
                    "confidence": round(float(verdict.confidence), 3),
                    "thesis_type": verdict.thesis_type,
                    "direction": strategy.direction,
                    "strength": round(float(strategy.strength), 3),
                    "intended_horizon_bars": int(strategy.intended_horizon_bars or 0),
                    "reason_codes": verdict.reason_codes,
                    "_obj": verdict,
                    "_strategy": strategy,
                },
            )
        except Exception as exc:
            return LayerTrace(name="thesis", ok=False, error=f"{type(exc).__name__}: {exc}")

    def _run_gates(
        self,
        pred_ctx: Dict[str, Any],
        gate_head: Any,
        df5m: Optional[pd.DataFrame],
        *,
        scenario: Optional[Dict[str, Any]] = None,
    ) -> LayerTrace:
        from agent.core.ml_validator import (
            build_ml_validation_from_prediction,
            apply_gates_to_ml_validation,
        )
        from agent.core.v43_signal_gates import (
            V43GateState,
            apply_gate5_min_edge,
            apply_gate5_min_edge_short,
            apply_post_threshold_gates,
            apply_post_threshold_gates_short,
        )
        from agent.core.v43_market_frames import closed_5m_bar_index
        from agent.core.config import settings
        try:
            eps = float(getattr(settings, "jacksparrow_v43_near_threshold_epsilon", 0.0) or 0.0)
            short_enabled = bool(getattr(settings, "jacksparrow_v43_short_execution_enabled", False))

            ml_validation = build_ml_validation_from_prediction(
                pred_ctx,
                pred_confidence=float(pred_ctx.get("model_confidence", 0.5)),
                pred_value=float(pred_ctx.get("model_prediction", 0.0)),
                eps=eps,
                short_enabled=short_enabled,
            )
            proba = ml_validation.expected_return
            boost = (scenario or {}).get("ml_expected_return_boost")
            if boost is not None:
                try:
                    proba = float(proba) + float(boost)
                except (TypeError, ValueError):
                    pass
            thr = ml_validation.threshold
            short_thr = ml_validation.short_threshold
            raw_long = ml_validation.raw_long
            raw_short = ml_validation.raw_short

            bar_idx = closed_5m_bar_index(df5m) if isinstance(df5m, pd.DataFrame) else 0
            gate_state = V43GateState()  # fresh state per scenario (no debounce carry-over)

            t0 = time.perf_counter()
            final_long = False
            final_short = False
            reject_tail = "below_threshold"
            gate_reject_reason = ""

            if raw_long:
                gr2 = apply_post_threshold_gates(
                    raw_long=raw_long,
                    regime=str(gate_head.regime or "neutral"),
                    current_bar_index=bar_idx,
                    has_open_position=False,
                    state=gate_state,
                )
                if gr2.allow:
                    g5 = apply_gate5_min_edge(proba, thr, gate_state)
                    final_long = bool(g5.allow)
                    reject_tail = g5.reject_reason or "min_edge_cost" if not final_long else "gates_passed_long"
                else:
                    reject_tail = gr2.reject_reason or "gate2_reject"
                gate_reject_reason = "" if final_long else reject_tail
            elif raw_short and short_enabled:
                gr2s = apply_post_threshold_gates_short(
                    raw_short=raw_short,
                    regime=str(gate_head.regime or "neutral"),
                    current_bar_index=bar_idx,
                    has_open_position=False,
                    state=gate_state,
                )
                if gr2s.allow:
                    g5s = apply_gate5_min_edge_short(proba, short_thr, gate_state)
                    final_short = bool(g5s.allow)
                    reject_tail = g5s.reject_reason or "min_edge_cost" if not final_short else "gates_passed_short"
                else:
                    reject_tail = gr2s.reject_reason or "gate2_reject_short"
                gate_reject_reason = "" if final_short else reject_tail
            else:
                gate_reject_reason = reject_tail

            gate_reject = None if (final_long or final_short) else gate_reject_reason
            apply_gates_to_ml_validation(
                ml_validation,
                final_long=final_long,
                final_short=final_short,
                gate_reject=gate_reject,
            )
            ms = (time.perf_counter() - t0) * 1000.0

            return LayerTrace(
                name="ml_gates",
                ok=True,
                duration_ms=ms,
                output={
                    "expected_return": round(float(proba), 6),
                    "threshold": round(float(thr), 6),
                    "short_threshold": round(float(short_thr), 6),
                    "raw_long": raw_long,
                    "raw_short": raw_short,
                    "final_long": final_long,
                    "final_short": final_short,
                    "gate_reject": gate_reject,
                    "_obj": ml_validation,
                },
            )
        except Exception as exc:
            return LayerTrace(name="ml_gates", ok=False, error=f"{type(exc).__name__}: {exc}")

    def _run_scorer(
        self,
        strategy_candidate: Any,
        ml_validation: Any,
        structure: Any,
    ) -> LayerTrace:
        from agent.core.trade_scorer import score_trade_setup
        from agent.core.ml_validator import ml_confirms_direction
        from agent.core.config import settings
        try:
            if strategy_candidate is None or ml_validation is None or structure is None:
                return LayerTrace(name="trade_scorer", ok=False, error="missing upstream object")

            eps = float(getattr(settings, "jacksparrow_v43_near_threshold_epsilon", 0.0) or 0.0)
            ml_confirms = (
                ml_confirms_direction(ml_validation, strategy_candidate.direction, eps=eps, require_gated=True)
                if strategy_candidate.direction != "FLAT"
                else False
            )
            trade_score, ms = self._timed_sync(
                score_trade_setup,
                strategy=strategy_candidate,
                ml_validation=ml_validation,
                structure=structure,
                ml_confirms=ml_confirms,
            )
            min_score = float(getattr(settings, "agent_trade_score_min", 70.0) or 70.0)

            return LayerTrace(
                name="trade_scorer",
                ok=True,
                duration_ms=ms,
                output={
                    "score": round(float(trade_score.score), 2),
                    "passed": trade_score.passed,
                    "min_required": min_score,
                    "ml_confirms": ml_confirms,
                    "components": {k: round(float(v), 2) for k, v in trade_score.components.items()},
                    "reason_codes": trade_score.reason_codes,
                    "_obj": trade_score,
                },
            )
        except Exception as exc:
            return LayerTrace(name="trade_scorer", ok=False, error=f"{type(exc).__name__}: {exc}")

    def _run_policy(
        self,
        pred_ctx: Dict[str, Any],
        ml_validation: Any,
        strategy_candidate: Any,
        trade_score: Any,
        mh_evidence: Any,
        regime: str,
        closed_feats: Dict[str, Any],
    ) -> LayerTrace:
        from agent.core.agent_policy_engine import agent_policy_engine
        from agent.core.ml_validator import ml_candidate_signal_from_validation
        from agent.events.schemas import MLEvidenceSnapshot
        try:
            ml_sig, ml_conf, ml_size = ml_candidate_signal_from_validation(
                ml_validation, prefer_gated=True
            )
            ml_evidence = MLEvidenceSnapshot(
                symbol=self.symbol,
                source="v43_orchestrator",
                ml_candidate_signal=ml_sig,
                ml_candidate_confidence=ml_conf,
                ml_candidate_position_size=ml_size,
                v43_gate_reject=ml_validation.gate_reject,
                v43_regime=regime,
                thesis_signal=strategy_candidate.signal if strategy_candidate else None,
                trade_score=float(trade_score.score) if trade_score else None,
                ml_confirms=bool(ml_validation.final_long or ml_validation.final_short),
            )

            market_context = {
                "symbol": self.symbol,
                "features": {str(k): float(v) for k, v in closed_feats.items() if v == v},
                "regime": regime,
                "v43_regime": regime,
                "trade_score": trade_score.to_dict() if trade_score else {},
                "strategy_candidate": strategy_candidate.to_dict() if strategy_candidate else {},
                "ml_validation": ml_validation.to_dict() if ml_validation else {},
                "multi_horizon_evidence": mh_evidence.to_dict() if mh_evidence else {},
            }

            verdict, ms = self._timed_sync(
                agent_policy_engine.evaluate,
                ml_evidence=ml_evidence,
                conclusion="",
                market_context=market_context,
            )

            return LayerTrace(
                name="policy_engine",
                ok=True,
                duration_ms=ms,
                output={
                    "signal": verdict.signal,
                    "confidence": round(float(verdict.confidence), 3),
                    "position_size": round(float(verdict.position_size), 4),
                    "adopted_ml_candidate": verdict.adopted_ml_candidate,
                    "reason_codes": list(verdict.reason_codes),
                    "ml_candidate_signal": ml_sig,
                    "_obj": verdict,
                },
            )
        except Exception as exc:
            return LayerTrace(name="policy_engine", ok=False, error=f"{type(exc).__name__}: {exc}")

    def _run_portfolio_guard(
        self,
        policy_verdict: Any,
        portfolio_state: Dict[str, Any],
        *,
        scenario: Optional[Dict[str, Any]] = None,
    ) -> LayerTrace:
        from agent.core.portfolio_intelligence import (
            build_snapshot_from_context,
            evaluate_portfolio_guard,
        )
        try:
            if policy_verdict is None:
                return LayerTrace(name="portfolio_guard", ok=False, error="no policy verdict")

            if scenario is None or "portfolio_state" not in scenario:
                return LayerTrace(
                    name="portfolio_guard",
                    ok=True,
                    duration_ms=0.0,
                    output={
                        "action": "allow",
                        "heat_ratio": 0.0,
                        "side_concentration": 0.0,
                        "allowed_size_fraction": round(
                            float(policy_verdict.position_size or 0.0), 4
                        ),
                        "shadow_only": False,
                        "reason_codes": ["portfolio_guard_skipped_no_fixture"],
                        "portfolio_equity": 0.0,
                        "open_positions_count": 0,
                        "_obj": None,
                    },
                )

            # Build open_positions list from portfolio_state for snapshot
            default_side = str((scenario or {}).get("portfolio_position_side") or "LONG").upper()
            positions_raw = []
            for sym, pdata in (portfolio_state.get("positions") or {}).items():
                if isinstance(pdata, dict) and pdata.get("status") == "open":
                    side = str(pdata.get("side") or default_side).upper()
                    if side not in ("LONG", "SHORT"):
                        side = default_side
                    positions_raw.append({
                        "symbol": sym,
                        "side": side,
                        "size": float(pdata.get("size", 1.0)),
                        "notional_usd": float(pdata.get("notional", 1000.0)),
                    })

            context = {
                "portfolio_value": float(portfolio_state.get("portfolio_value", 10000.0)),
                "portfolio_equity_usd": float(portfolio_state.get("portfolio_value", 10000.0)),
                "open_positions": positions_raw,
            }
            snapshot = build_snapshot_from_context(context)

            guard, ms = self._timed_sync(
                evaluate_portfolio_guard,
                snapshot,
                symbol=self.symbol,
                proposed_signal=policy_verdict.signal,
                proposed_size_fraction=float(policy_verdict.position_size or 0.05),
            )

            return LayerTrace(
                name="portfolio_guard",
                ok=True,
                duration_ms=ms,
                output={
                    "action": guard.action,
                    "heat_ratio": round(float(guard.heat_ratio), 3),
                    "side_concentration": round(float(guard.side_concentration_ratio), 3),
                    "allowed_size_fraction": round(float(guard.allowed_size_fraction), 4),
                    "shadow_only": guard.shadow_only,
                    "reason_codes": list(guard.reason_codes),
                    "portfolio_equity": round(float(snapshot.portfolio_equity_usd), 2),
                    "open_positions_count": len(snapshot.positions),
                    "_obj": guard,
                },
            )
        except Exception as exc:
            return LayerTrace(name="portfolio_guard", ok=False, error=f"{type(exc).__name__}: {exc}")

    # ──────────────────────────────────────────────────────────────────────
    # Batch
    # ──────────────────────────────────────────────────────────────────────

    async def run_all(self, scenarios: List[Dict[str, Any]]) -> List[ScenarioTrace]:
        traces = []
        for sc in scenarios:
            logger.info("scenario_runner_start", name=sc["scenario_name"])
            trace = await self.run(sc)
            logger.info(
                "scenario_runner_done",
                name=sc["scenario_name"],
                total_ms=round(trace.total_ms, 1),
                error=trace.error,
            )
            traces.append(trace)
        return traces
