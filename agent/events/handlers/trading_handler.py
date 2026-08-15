"""
Trading event handler.

Bridges DecisionReadyEvent to RiskApprovedEvent by performing risk validation
and publishing RiskApprovedEvent when trades are approved.
"""

from typing import Any, Dict, Optional
from datetime import datetime, timezone
import asyncio
import structlog
import time

from agent.events.schemas import DecisionReadyEvent, RiskApprovedEvent, EventType
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager
from agent.core.config import settings
from agent.core.futures_utils import (
    entry_lots_from_portfolio_margin,
    entry_leg_fees_usd,
    margin_required_inr,
    max_affordable_lots_from_cash,
    price_to_lots,
)
from agent.core.sl_tp import compute_stop_take_prices
from agent.core.product_specs import get_contract_specs
from agent.core.decision_timestamp import decision_payload_age_seconds
from agent.core.signal_filter import EntrySignalFilter
from agent.core.redis_config import get_cache

logger = structlog.get_logger()

# Defaults live in config (`Settings.trade_signal_debounce_seconds`,
# `Settings.min_risk_reward_ratio`, `Settings.adx_ranging_threshold`).
DEFAULT_TRADE_SIGNAL_DEBOUNCE_SECONDS = 10
DEFAULT_MIN_RISK_REWARD_RATIO = 1.2
DEFAULT_ADX_RANGING_THRESHOLD = 20.0


def _tf_bar_seconds(tf: str) -> int:
    """Bar duration in seconds from timeframe string (e.g. 5m, 15m, 1h)."""
    t = (tf or "15m").strip().lower()
    if t.endswith("m") and t[:-1].isdigit():
        return int(t[:-1]) * 60
    if t.endswith("h") and t[:-1].isdigit():
        return int(t[:-1]) * 3600
    return 900


def _default_learning_stub() -> Any:
    """Lightweight stub so tests can monkeypatch calibrate_runtime_confidence."""

    class _LearningStub:
        async def calibrate_runtime_confidence(self, confidence: float, model_predictions: Any = None) -> float:
            return float(confidence)

    return _LearningStub()


class TradingEventHandler:
    """Handler that bridges DecisionReadyEvent to RiskApprovedEvent."""

    def __init__(self, risk_manager, delta_client=None, execution_module=None, learning_system=None):
        """Initialize trading event handler."""
        self.risk_manager = risk_manager
        self.context_manager = context_manager
        self.delta_client = delta_client
        self.execution_module = execution_module
        self.learning_system = (
            learning_system if learning_system is not None else _default_learning_stub()
        )
        # Deduplicate: last (symbol, side) -> timestamp of last RiskApproved published
        self._last_risk_approved: Dict[str, float] = {}
        self._entry_signal_filter = EntrySignalFilter(
            max_trades_per_hour=int(getattr(settings, "max_trades_per_hour", 0) or 0),
            min_breakout_score=float(getattr(settings, "entry_min_breakout_score", 0.0) or 0.0),
        )
        self._last_trade_wall_time: float = 0.0
        self._trades_day_key: str = ""
        self._trades_today_by_tf: Dict[str, int] = {}

    def _debounce_key(self, symbol: str, side: str) -> str:
        """Key for debounce: same symbol+side within window = duplicate."""
        return f"{symbol}:{side}"

    def _should_skip_debounce(self, symbol: str, side: str) -> bool:
        """True if we should skip publishing (duplicate within window)."""
        key = self._debounce_key(symbol, side)
        now = time.time()
        last = self._last_risk_approved.get(key, 0)
        debounce_seconds = int(
            getattr(settings, "trade_signal_debounce_seconds", DEFAULT_TRADE_SIGNAL_DEBOUNCE_SECONDS)
            or 0
        )
        if debounce_seconds <= 0:
            return False
        if now - last < debounce_seconds:
            return True
        self._last_risk_approved[key] = now
        return False

    def _check_entry_profit_potential(
        self,
        entry_price: float,
        side: str,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> bool:
        """True if risk/reward ratio meets minimum (entry profit gate)."""
        if stop_loss_pct <= 0 or take_profit_pct <= 0:
            return True  # No stops configured, allow
        if side == "long" or side == "BUY":
            risk = entry_price * stop_loss_pct
            reward = entry_price * take_profit_pct
        else:
            risk = entry_price * stop_loss_pct
            reward = entry_price * take_profit_pct
        if risk <= 0:
            return True
        ratio = reward / risk
        min_ratio = float(
            getattr(settings, "min_risk_reward_ratio", DEFAULT_MIN_RISK_REWARD_RATIO)
            or DEFAULT_MIN_RISK_REWARD_RATIO
        )
        return ratio >= min_ratio

    def _log_entry_rejected(
        self,
        reason: str,
        *,
        symbol: str,
        signal: Optional[str],
        event_id: str,
        **context: Any,
    ) -> None:
        """Emit standardized reject logs for trade-entry diagnostics."""
        logger.info(
            "trading_entry_rejected",
            reason=reason,
            symbol=symbol,
            signal=signal,
            event_id=event_id,
            **context,
        )
        try:
            from agent.core.signal_audit_md import append_entry_rejected

            append_entry_rejected(
                reason=reason,
                symbol=symbol,
                signal=signal,
                event_id=event_id,
                extra=dict(context) if context else None,
            )
        except Exception as e:
            logger.warning(
                "signal_audit_entry_rejected_append_failed",
                symbol=symbol,
                reason=reason,
                error=str(e),
            )

    def _reasoning_pipeline_diagnostics(
        self, reasoning_chain: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Structured fields to distinguish HOLD-at-synthesis vs execution-layer rejects."""
        if not isinstance(reasoning_chain, dict):
            return {}
        out: Dict[str, Any] = {
            "reasoning_final_confidence": reasoning_chain.get("final_confidence"),
            "reasoning_conclusion": (reasoning_chain.get("conclusion") or "")[:200],
        }
        steps = reasoning_chain.get("steps") or []
        if isinstance(steps, list):
            for s in steps:
                if not isinstance(s, dict):
                    continue
                sn = s.get("step_number")
                if sn == 5:
                    out["synthesis_step5_description"] = (s.get("description") or "")[:240]
                    out["synthesis_step5_confidence"] = s.get("confidence")
                elif sn == 6:
                    out["adjudication_step6_description"] = (s.get("description") or "")[:240]
                    out["adjudication_step6_confidence"] = s.get("confidence")
                elif sn == 7:
                    out["calibration_step7_confidence"] = s.get("confidence")
                    meta = s.get("step_metadata")
                    if isinstance(meta, dict):
                        out["signal_strength"] = meta.get("signal_strength")
                        out["entry_proba_margin_mean"] = meta.get(
                            "entry_proba_margin_mean"
                        )
        hold_bucket = None
        conclusion = (out.get("reasoning_conclusion") or "").lower()
        if "dead zone" in conclusion:
            hold_bucket = "mtf_dead_zone"
        elif "below entry edge" in conclusion:
            hold_bucket = "mtf_entry_edge"
        elif "not confirming trend" in conclusion:
            hold_bucket = "mtf_not_confirming_trend"
        elif "trend neutral" in conclusion:
            hold_bucket = "mtf_trend_neutral"
        elif "mixed signals" in conclusion:
            hold_bucket = "consensus_in_hold_band"
        if hold_bucket:
            out["hold_bucket"] = hold_bucket
        mc = reasoning_chain.get("market_context")
        if isinstance(mc, dict):
            bar_idx = mc.get("v43_closed_bar_index")
            if bar_idx is not None:
                out["v43_closed_bar_index"] = bar_idx
        return out

    def _summarize_model_entry_proba(
        self, model_predictions: Any
    ) -> Dict[str, Any]:
        """
        Summarize predicted class probabilities when model_predictions preserve
        model context (e.g. v4 entry_proba in context).
        """
        if not isinstance(model_predictions, list) or not model_predictions:
            return {}

        sell_vals: list[float] = []
        hold_vals: list[float] = []
        buy_vals: list[float] = []
        max_conf_vals: list[float] = []

        for mp in model_predictions:
            if not isinstance(mp, dict):
                continue
            ctx = mp.get("context") or {}
            if not isinstance(ctx, dict):
                continue
            entry_proba = ctx.get("entry_proba") or {}
            if not isinstance(entry_proba, dict):
                continue
            sell = entry_proba.get("sell")
            hold = entry_proba.get("hold")
            buy = entry_proba.get("buy")
            if sell is None or hold is None or buy is None:
                continue

            try:
                sell_f = float(sell)
                hold_f = float(hold)
                buy_f = float(buy)
            except (TypeError, ValueError):
                continue

            sell_vals.append(sell_f)
            hold_vals.append(hold_f)
            buy_vals.append(buy_f)
            max_conf_vals.append(max(sell_f, hold_f, buy_f))

        if not sell_vals:
            return {}

        n = len(sell_vals)
        return {
            "entry_proba_models": n,
            "entry_proba_sell_mean": sum(sell_vals) / n,
            "entry_proba_hold_mean": sum(hold_vals) / n,
            "entry_proba_buy_mean": sum(buy_vals) / n,
            "entry_proba_max_conf_mean": sum(max_conf_vals) / n,
        }

    async def handle_decision_ready_for_trading(self, event: DecisionReadyEvent):
        """Handle decision ready event - validate risk and publish RiskApprovedEvent if approved.

        For BUY/SELL signals, performs risk validation and publishes RiskApprovedEvent
        to trigger trade execution. Skips HOLD signals.

        Args:
            event: Decision ready event with signal, confidence, position_size
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol", settings.trading_symbol or "BTCUSD")
            signal = payload.get("signal")
            confidence = payload.get("confidence", 0.0)
            position_size = payload.get("position_size", 0.0)

            now_utc = datetime.now(timezone.utc)
            hour_bucket_utc = now_utc.strftime("%Y-%m-%dT%H:00Z")
            reasoning_chain = payload.get("reasoning_chain") or {}
            model_predictions = (
                reasoning_chain.get("model_predictions") if isinstance(reasoning_chain, dict) else None
            ) or []
            features = (
                (payload.get("reasoning_chain") or {}).get("market_context", {}).get("features", {})
                if isinstance(payload.get("reasoning_chain"), dict)
                else {}
            )
            if not isinstance(features, dict):
                features = {}
            mc = (
                (payload.get("reasoning_chain") or {}).get("market_context", {})
                if isinstance(payload.get("reasoning_chain"), dict)
                else {}
            )
            v43_ex = mc.get("v43_execution_profile") if isinstance(mc, dict) else None
            v43_exec_enabled = isinstance(v43_ex, dict) and bool(v43_ex.get("enabled"))
            execution_plan = (
                mc.get("execution_plan") if isinstance(mc, dict) else None
            )
            if not isinstance(execution_plan, dict):
                execution_plan = {}
            gates_on = bool(getattr(settings, "entry_gates_enabled", False))
            transformer_gates = gates_on and (
                bool(getattr(settings, "transformer_entry_gates", False))
                or bool(getattr(settings, "ai_signal_minimal_entry_gates", False))
            )
            legacy_feature_gates = gates_on and bool(
                getattr(settings, "legacy_feature_entry_gates", False)
            )
            # Legacy alias: minimal_entry historically skipped most feature gates.
            minimal_entry = transformer_gates and not legacy_feature_gates
            entry_proba_summary = self._summarize_model_entry_proba(model_predictions)
            diagnostics_base: Dict[str, Any] = {
                "hour_bucket_utc": hour_bucket_utc,
                **entry_proba_summary,
                **self._reasoning_pipeline_diagnostics(
                    reasoning_chain if isinstance(reasoning_chain, dict) else {}
                ),
            }
            raw_confidence = confidence
            diagnostics_base["raw_confidence"] = raw_confidence
            diagnostics_base["calibrated_confidence"] = confidence
            diagnostics_base["entry_gates_enabled"] = gates_on

            try:
                raw_ai_gate = max(0.0, min(1.0, float(payload.get("confidence", 0.0) or 0.0)))
            except (TypeError, ValueError):
                raw_ai_gate = 0.0
            hold_floor = float(
                getattr(settings, "transformer_confidence_hold_floor", 0.0) or 0.0
            )
            ai_floor = hold_floor if transformer_gates else max(
                0.0,
                min(1.0, float(getattr(settings, "ai_signal_min_entry_confidence", 0.7) or 0.7)),
            )
            diagnostics_base["raw_ai_signal_confidence"] = raw_ai_gate
            diagnostics_base["ai_signal_min_entry_confidence_floor"] = ai_floor
            diagnostics_base["ai_signal_minimal_entry_gates"] = minimal_entry
            diagnostics_base["transformer_entry_gates"] = transformer_gates
            diagnostics_base["legacy_feature_entry_gates"] = legacy_feature_gates
            diagnostics_base["decision_path"] = (
                mc.get("decision_path") if isinstance(mc, dict) else None
            ) or "transformer_agent_synthesis"

            # HOLD: optional gated-ML reversal exit while positioned (PIPE-01)
            if signal == "HOLD" or not signal:
                rc = payload.get("reasoning_chain") or {}
                if isinstance(rc, dict) and await self._try_ml_reversal_exit_while_policy_hold(
                    symbol=symbol,
                    event_id=event.event_id,
                    reasoning_chain=rc,
                    diagnostics_base=diagnostics_base,
                ):
                    return
                self._log_entry_rejected(
                    "hold_at_synthesis",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    **diagnostics_base,
                )
                return

            if gates_on and transformer_gates and raw_ai_gate < hold_floor:
                self._log_entry_rejected(
                    "low_ai_signal_confidence",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    min_entry_confidence=hold_floor,
                    **diagnostics_base,
                )
                return
            if (
                gates_on
                and not transformer_gates
                and bool(getattr(settings, "ai_signal_minimal_entry_gates", False))
                and raw_ai_gate < ai_floor
            ):
                self._log_entry_rejected(
                    "low_ai_signal_confidence",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    min_entry_confidence=ai_floor,
                    **diagnostics_base,
                )
                return

            # Signal expiry (only when entry gates enabled)
            if gates_on and (transformer_gates or not minimal_entry):
                if payload.get("server_timestamp_ms") is None:
                    payload["server_timestamp_ms"] = int(
                        getattr(event, "timestamp", now_utc).timestamp() * 1000
                    )
                try:
                    age = decision_payload_age_seconds(payload)
                    if age is None:
                        raise ValueError("unparseable decision timestamp")
                    max_age = int(
                        getattr(settings, "max_signal_age_seconds", 45) or 45
                    )
                    if age > max_age:
                        self._log_entry_rejected(
                            "stale_signal_reject",
                            symbol=symbol,
                            signal=signal,
                            event_id=event.event_id,
                            age_seconds=round(age, 3),
                            max_signal_age_seconds=max_age,
                            server_timestamp_ms=payload.get("server_timestamp_ms"),
                            **diagnostics_base,
                        )
                        return
                except Exception as e:
                    logger.warning(
                        "stale_signal_age_check_failed",
                        symbol=symbol,
                        event_id=event.event_id,
                        error=str(e),
                        exc_info=True,
                    )
                    self._log_entry_rejected(
                        "stale_signal_timestamp_unverifiable",
                        symbol=symbol,
                        signal=signal,
                        event_id=event.event_id,
                        **diagnostics_base,
                    )
                    return

            signal_path_diag: Dict[str, Any] = {}
            if execution_plan:
                signal_path_diag = {
                    "execution_plan": True,
                    "rr_soft_action": execution_plan.get("rr_soft_action"),
                    "size_scale": execution_plan.get("size_scale"),
                }
            if signal in ("BUY", "STRONG_BUY"):
                side = "BUY"
                risk_side = "long"
            elif signal in ("SELL", "STRONG_SELL"):
                side = "SELL"
                risk_side = "short"
            else:
                self._log_entry_rejected(
                    "unexpected_hold_signal",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    **diagnostics_base,
                )
                return

            # Signal-reversal exit: if open position contradicts signal, close first and return
            if self.execution_module:
                open_pos = self.execution_module.position_manager.get_position(symbol)
                if (
                    bool(getattr(settings, "exchange_position_reconcile_enabled", True))
                    and (not open_pos or open_pos.get("status") != "open")
                ):
                    try:
                        from agent.core.mcp_orchestrator import _exchange_has_open_position_async
                        from agent.core.position_reconcile import reconcile_positions_with_exchange

                        if await _exchange_has_open_position_async(symbol):
                            await reconcile_positions_with_exchange(self.execution_module)
                            open_pos = self.execution_module.position_manager.get_position(symbol)
                    except Exception as e:
                        logger.warning(
                            "exchange_position_reconcile_failed",
                            symbol=symbol,
                            error=str(e),
                            exc_info=True,
                        )
                if open_pos and open_pos.get("status") == "open":
                    pos_side = open_pos.get("side", "")
                    if (pos_side == "long" and signal in ("STRONG_SELL", "SELL")) or (
                        pos_side == "short" and signal in ("STRONG_BUY", "BUY")
                    ):
                        logger.info(
                            "signal_reversal_exit",
                            symbol=symbol,
                            pos=pos_side,
                            signal=signal,
                            event_id=event.event_id,
                        )
                        close_result = await self.execution_module.close_position(
                            symbol, exit_reason="signal_reversal"
                        )
                        if not close_result.success:
                            return
                        # Fall through to size and enter on the new side without waiting for next bar.
                    elif (pos_side == "long" and signal in ("BUY", "STRONG_BUY")) or (
                        pos_side == "short" and signal in ("SELL", "STRONG_SELL")
                    ):
                        self._log_entry_rejected(
                            "open_position_blocks_entry",
                            symbol=symbol,
                            signal=signal,
                            event_id=event.event_id,
                            position_side=pos_side,
                            **diagnostics_base,
                        )
                        return

            if gates_on and transformer_gates:
                # Soft bands already applied in policy; only hard-reject below hold floor.
                if float(raw_confidence or 0.0) < hold_floor:
                    self._log_entry_rejected(
                        "low_confidence_reject",
                        symbol=symbol,
                        signal=signal,
                        event_id=event.event_id,
                        confidence=raw_confidence,
                        calibrated_confidence=confidence,
                        threshold=hold_floor,
                        config_min_confidence_threshold=hold_floor,
                        **diagnostics_base,
                    )
                    return
            elif gates_on and minimal_entry:
                confidence = raw_ai_gate
            elif gates_on and v43_exec_enabled:
                confidence = max(
                    float(confidence or 0.0),
                    float(getattr(settings, "min_confidence_threshold", 0.52) or 0.52) * 0.85,
                )
            elif gates_on:
                eff_min_conf = float(
                    getattr(settings, "transformer_min_confidence", None)
                    or getattr(settings, "min_confidence_threshold", 0.52)
                    or 0.52
                )
                if bool(getattr(settings, "paper_trade_validation_mode", False)):
                    eff_min_conf = float(
                        getattr(settings, "paper_trade_validation_min_confidence", 0.45) or 0.45
                    )
                if raw_confidence < eff_min_conf:
                    self._log_entry_rejected(
                        "low_confidence_reject",
                        symbol=symbol,
                        signal=signal,
                        event_id=event.event_id,
                        confidence=raw_confidence,
                        calibrated_confidence=confidence,
                        threshold=eff_min_conf,
                        metadata_recommended_threshold=None,
                        config_min_confidence_threshold=settings.min_confidence_threshold,
                        **diagnostics_base,
                    )
                    return

            # Get portfolio value and current price from live market data
            state = self.context_manager.get_state()
            entry_price = await self._get_current_price(symbol, state)
            if entry_price is None or entry_price <= 0:
                self._log_entry_rejected(
                    "no_price",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    **diagnostics_base,
                )
                return

            if not minimal_entry and legacy_feature_gates:
                vol = features.get("volatility")
                if vol is None and not v43_exec_enabled:
                    self._log_entry_rejected(
                        "missing_volatility_reject",
                        symbol=symbol,
                        signal=signal,
                        event_id=event.event_id,
                        **diagnostics_base,
                    )
                    return
                try:
                    vol_f = float(vol) if vol is not None else 0.0
                except (TypeError, ValueError):
                    if not v43_exec_enabled:
                        self._log_entry_rejected(
                            "invalid_volatility",
                            symbol=symbol,
                            signal=signal,
                            event_id=event.event_id,
                            volatility=vol,
                            **diagnostics_base,
                        )
                        return
                    vol_f = 0.0
                min_vol = float(getattr(settings, "entry_min_volatility_for_trade", 0.0) or 0.0)
                if min_vol > 0 and not v43_exec_enabled:
                    try:
                        if vol_f < min_vol:
                            self._log_entry_rejected(
                                "low_volatility",
                                symbol=symbol,
                                signal=signal,
                                event_id=event.event_id,
                                volatility=vol_f,
                                min_volatility=min_vol,
                                **diagnostics_base,
                            )
                            return
                    except Exception as e:
                        logger.warning(
                            "entry_volatility_gate_failed",
                            symbol=symbol,
                            error=str(e),
                            exc_info=True,
                        )
                min_atr_pct = float(getattr(settings, "entry_min_atr_pct_of_price", 0.0) or 0.0)
                if min_atr_pct > 0 and entry_price > 0 and not v43_exec_enabled:
                    atr_raw = features.get("atr_14")
                    if atr_raw is not None:
                        try:
                            atr_f = float(atr_raw)
                            if atr_f / entry_price < min_atr_pct:
                                self._log_entry_rejected(
                                    "low_atr",
                                    symbol=symbol,
                                    signal=signal,
                                    event_id=event.event_id,
                                    atr_pct=atr_f / entry_price,
                                    min_atr_pct=min_atr_pct,
                                    **diagnostics_base,
                                )
                                return
                        except (TypeError, ValueError):
                            pass
            min_lot_size = max(1, int(getattr(settings, "min_lot_size", 1) or 1))
            fixed_lots = max(1, int(getattr(settings, "fixed_lot_size", 1) or 1))
            fixed_lots = max(min_lot_size, fixed_lots)

            try:
                conf_f = float(confidence) if confidence is not None else 0.5
            except (TypeError, ValueError):
                conf_f = 0.5
            conf_f = max(0.0, min(1.0, conf_f))

            usdinr_rate = await self._get_usdinr_rate(state)
            available_cash_inr = await self._get_available_cash_inr(state, symbol)
            portfolio_value_inr = await self._get_portfolio_value_inr(
                state, symbol, available_cash_inr=available_cash_inr
            )

            specs = await get_contract_specs(symbol)
            cv = float(specs.contract_value_btc)
            tick_sz = float(specs.tick_size)
            taker_rate = float(
                specs.taker_commission_rate
                if specs.taker_commission_rate is not None
                else getattr(settings, "taker_fee_rate", 0.0005)
            )
            slip_bps = float(getattr(settings, "slippage_bps", 5.0) or 5.0)

            entry_portfolio_frac = max(
                0.01,
                min(
                    1.0,
                    float(
                        getattr(settings, "entry_portfolio_margin_fraction", 0.60) or 0.60
                    ),
                ),
            )
            if execution_plan.get("size_fraction") is not None:
                try:
                    plan_frac = float(execution_plan.get("size_fraction") or 0.0)
                    if plan_frac > 0:
                        entry_portfolio_frac = max(0.01, min(1.0, plan_frac))
                except (TypeError, ValueError):
                    pass
            leverage = max(1, int(getattr(settings, "isolated_margin_leverage", 5) or 5))
            settings_max_lots = int(getattr(settings, "max_lots_per_order", 100) or 100)
            if getattr(settings, "portfolio_fraction_lot_sizing", True):
                from agent.core.futures_utils import max_lots_from_portfolio_budget

                max_lots = max_lots_from_portfolio_budget(
                    portfolio_value_inr=portfolio_value_inr,
                    margin_fraction=entry_portfolio_frac,
                    usdinr_rate=usdinr_rate,
                    btc_price=entry_price,
                    leverage=leverage,
                    contract_value_btc=cv,
                    settings_cap=settings_max_lots,
                    min_lots=min_lot_size,
                )
            else:
                max_lots = settings_max_lots
            margin_inr = 0.0

            fee_reserve = float(
                getattr(settings, "entry_fee_reserve_fraction", 0.02) or 0.02
            )
            if getattr(settings, "portfolio_fraction_lot_sizing", True):
                entry_lots, margin_inr = entry_lots_from_portfolio_margin(
                    portfolio_value_inr=portfolio_value_inr,
                    margin_fraction=entry_portfolio_frac,
                    usdinr_rate=usdinr_rate,
                    btc_price=entry_price,
                    leverage=leverage,
                    contract_value_btc=cv,
                    max_lots=max_lots,
                    min_lots=min_lot_size,
                    available_cash_inr=available_cash_inr,
                    fee_reserve_fraction=fee_reserve,
                    taker_fee_rate=taker_rate,
                    slippage_bps=slip_bps,
                )
            elif v43_exec_enabled and isinstance(v43_ex, dict):
                alloc_frac = max(
                    0.01,
                    min(
                        1.0,
                        float(v43_ex.get("margin_cap_fraction", 0.2) or 0.2),
                    ),
                )
                margin_inr = available_cash_inr * alloc_frac
                usd_margin = margin_inr / usdinr_rate if usdinr_rate > 0 else 0.0
                entry_lots = price_to_lots(
                    usd_margin=usd_margin,
                    btc_price=entry_price,
                    leverage=leverage,
                    contract_value_btc=cv,
                    max_lots=max_lots,
                    min_lots=min_lot_size,
                )
            elif getattr(settings, "use_notional_lot_sizing", False):
                alloc_frac = max(
                    0.01,
                    min(
                        1.0,
                        float(getattr(settings, "max_position_size", 0.1) or 0.1) * max(0.1, conf_f),
                    ),
                )
                margin_inr = available_cash_inr * alloc_frac
                usd_margin = margin_inr / usdinr_rate if usdinr_rate > 0 else 0.0
                entry_lots = price_to_lots(
                    usd_margin=usd_margin,
                    btc_price=entry_price,
                    leverage=leverage,
                    contract_value_btc=cv,
                    max_lots=max_lots,
                    min_lots=min_lot_size,
                )
            else:
                entry_lots = fixed_lots

            affordable_lots = max_affordable_lots_from_cash(
                available_cash_inr=available_cash_inr,
                usdinr_rate=usdinr_rate,
                btc_price=entry_price,
                leverage=leverage,
                contract_value_btc=cv,
                fee_reserve_fraction=fee_reserve,
                taker_fee_rate=taker_rate,
                slippage_bps=slip_bps,
                min_lots=min_lot_size,
                max_lots=max_lots,
            )
            if affordable_lots <= 0:
                entry_lots = 0
            else:
                entry_lots = min(entry_lots, affordable_lots)
            # Avoid silent starve from size_scale: floor to min lot once if unscaled budget allows
            if (
                entry_lots < min_lot_size
                and affordable_lots >= min_lot_size
                and getattr(settings, "portfolio_fraction_lot_sizing", True)
            ):
                base_frac = float(
                    getattr(settings, "entry_portfolio_margin_fraction", 0.60) or 0.60
                )
                if entry_portfolio_frac < base_frac:
                    entry_lots = min_lot_size
                    logger.info(
                        "size_floored_to_min_lot",
                        symbol=symbol,
                        min_lot_size=min_lot_size,
                        size_fraction=entry_portfolio_frac,
                        base_fraction=base_frac,
                    )
            margin_inr = margin_required_inr(
                lots=entry_lots,
                btc_price_usd=entry_price,
                usdinr_rate=usdinr_rate,
                leverage=leverage,
                contract_value_btc=cv,
            )

            required_margin_inr = margin_inr
            fee_mode = (getattr(settings, "fee_accounting_mode", "split") or "split").lower()
            entry_fee_inr = 0.0
            if fee_mode == "split":
                entry_fee_usd = entry_leg_fees_usd(
                    entry_price,
                    float(entry_lots),
                    cv,
                    taker_rate,
                    slip_bps,
                )
                entry_fee_inr = entry_fee_usd * usdinr_rate
            required_total_inr = required_margin_inr + entry_fee_inr

            if gates_on and (required_total_inr <= 0 or available_cash_inr < required_total_inr):
                self._log_entry_rejected(
                    "insufficient_margin_inr",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    available_cash_inr=available_cash_inr,
                    required_margin_inr=required_margin_inr,
                    required_total_inr=required_total_inr,
                    entry_fee_inr=entry_fee_inr,
                    usdinr_rate=usdinr_rate,
                    leverage=leverage,
                    entry_lots=entry_lots,
                    **diagnostics_base,
                )
                return

            # Must match entry_portfolio_frac used for lot sizing (BUG-01: avoid 10% cap mismatch).
            proposed_size = entry_portfolio_frac

            if bool(getattr(settings, "exchange_position_reconcile_enabled", True)):
                try:
                    from agent.core.position_reconcile import (
                        is_reconcile_healthy,
                        reconcile_positions_with_exchange,
                    )

                    if not is_reconcile_healthy() and self.execution_module:
                        await reconcile_positions_with_exchange(self.execution_module)
                except Exception as exc:
                    logger.warning("pre_entry_reconcile_failed", error=str(exc))

            # Validate trade with risk manager (policy rejects only when ENTRY_GATES_ENABLED)
            validation = await self.risk_manager.validate_trade(
                symbol=symbol,
                side=risk_side,
                proposed_size=proposed_size,
                entry_price=entry_price,
                stop_loss=None,  # Execution will compute from config
                required_balance_override=required_margin_inr,
                available_balance_override=available_cash_inr,
            )

            if gates_on and not validation.get("approved", False):
                self._log_entry_rejected(
                    "risk_rejected",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    side=side,
                    risk_reason=validation.get("reason", "Unknown"),
                    minimal_entry=minimal_entry,
                    **diagnostics_base,
                )
                return

            # Deduplicate: one RiskApproved per (symbol, side) per time window.
            if gates_on and self._should_skip_debounce(symbol, side):
                self._log_entry_rejected(
                    "debounce",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    side=side,
                    debounce_seconds=int(
                        getattr(
                            settings,
                            "trade_signal_debounce_seconds",
                            DEFAULT_TRADE_SIGNAL_DEBOUNCE_SECONDS,
                        )
                        or 0
                    ),
                    **diagnostics_base,
                )
                return
            if not gates_on:
                self._last_risk_approved[self._debounce_key(symbol, side)] = time.time()

            # Path-pred / ATR / fixed SL/TP
            atr = features.get("atr_14")
            sl_tp_mode = str(getattr(settings, "sl_tp_mode", "path_pred") or "path_pred").lower()
            use_atr_sl_tp = bool(getattr(settings, "use_atr_scaled_sl_tp", False))
            stop_loss_price = None
            take_profit_price = None
            stop_pct = settings.stop_loss_percentage
            take_pct = settings.take_profit_percentage

            if (
                sl_tp_mode == "path_pred"
                and execution_plan.get("mfe") is not None
            ):
                try:
                    from agent.core.path_execution_plan import compute_path_stop_take_prices

                    stop_loss_price, take_profit_price, _, _ = compute_path_stop_take_prices(
                        float(entry_price),
                        signal=str(signal),
                        mfe=float(execution_plan.get("mfe") or 0.0),
                        mae=float(execution_plan.get("mae") or 0.0),
                        sl_adverse_mult=float(
                            getattr(settings, "path_sl_adverse_mult", 1.0) or 1.0
                        ),
                        tp_favorable_mult=float(
                            getattr(settings, "path_tp_favorable_mult", 1.0) or 1.0
                        ),
                        tick_size=tick_sz,
                    )
                    if execution_plan.get("stop_loss_pct") is not None:
                        stop_pct = float(execution_plan["stop_loss_pct"])
                    if execution_plan.get("take_profit_pct") is not None:
                        take_pct = float(execution_plan["take_profit_pct"])
                except Exception as exc:
                    logger.warning(
                        "path_pred_sl_tp_failed",
                        error=str(exc),
                        exc_info=True,
                    )
                    stop_loss_price = None
                    take_profit_price = None

            if stop_loss_price is None and use_atr_sl_tp and atr is not None:
                try:
                    atr_f = float(atr)
                    sl_mult = float(getattr(settings, "atr_sl_distance_mult", 1.0))
                    tp_mult = float(getattr(settings, "atr_tp_distance_mult", 1.5))
                    stop_loss_price, take_profit_price = compute_stop_take_prices(
                        entry_price,
                        side,
                        stop_pct,
                        take_pct,
                        use_atr_scaled=True,
                        atr_14=atr_f,
                        atr_sl_mult=sl_mult,
                        atr_tp_mult=tp_mult,
                        tick_size=tick_sz,
                    )
                except (TypeError, ValueError):
                    use_atr_sl_tp = False
                    stop_loss_price = None
                    take_profit_price = None

            # Hard profit_gate only under legacy feature gates (path R:R is soft upstream)
            if legacy_feature_gates and not transformer_gates:
                if use_atr_sl_tp and stop_loss_price is not None and take_profit_price is not None:
                    sl_pct_eff = abs(entry_price - stop_loss_price) / entry_price
                    tp_pct_eff = abs(take_profit_price - entry_price) / entry_price
                    if not self._check_entry_profit_potential(
                        entry_price, side, sl_pct_eff, tp_pct_eff
                    ):
                        self._log_entry_rejected(
                            "profit_gate",
                            symbol=symbol,
                            signal=signal,
                            event_id=event.event_id,
                            side=side,
                            entry_price=entry_price,
                            min_ratio=float(
                                getattr(
                                    settings, "min_risk_reward_ratio", DEFAULT_MIN_RISK_REWARD_RATIO
                                )
                                or DEFAULT_MIN_RISK_REWARD_RATIO
                            ),
                            **diagnostics_base,
                        )
                        return
                elif stop_loss_price is None:
                    stop_pct = settings.stop_loss_percentage
                    take_pct = settings.take_profit_percentage
                    if not self._check_entry_profit_potential(
                        entry_price, side, stop_pct, take_pct
                    ):
                        self._log_entry_rejected(
                            "profit_gate",
                            symbol=symbol,
                            signal=signal,
                            event_id=event.event_id,
                            side=side,
                            entry_price=entry_price,
                            min_ratio=float(
                                getattr(
                                    settings, "min_risk_reward_ratio", DEFAULT_MIN_RISK_REWARD_RATIO
                                )
                                or DEFAULT_MIN_RISK_REWARD_RATIO
                            ),
                            **diagnostics_base,
                        )
                        return

            # Legacy directional feature filters (off by default)
            if legacy_feature_gates and getattr(settings, "mtf_confirmation_enabled", False):
                trend_15m = features.get("trend_15m")
                if trend_15m is not None:
                    if signal in ("BUY", "STRONG_BUY") and trend_15m < 0:
                        self._log_entry_rejected(
                            "mtf_filter",
                            symbol=symbol,
                            signal=signal,
                            event_id=event.event_id,
                            trend_15m=trend_15m,
                            **diagnostics_base,
                        )
                        return
                    if signal in ("SELL", "STRONG_SELL") and trend_15m > 0:
                        self._log_entry_rejected(
                            "mtf_filter",
                            symbol=symbol,
                            signal=signal,
                            event_id=event.event_id,
                            trend_15m=trend_15m,
                            **diagnostics_base,
                        )
                        return

            if legacy_feature_gates and not v43_exec_enabled:
                adx = features.get("adx_14")
                adx_floor = float(
                    getattr(settings, "adx_ranging_threshold", DEFAULT_ADX_RANGING_THRESHOLD)
                    or DEFAULT_ADX_RANGING_THRESHOLD
                )
                if adx is not None and float(adx) < adx_floor and signal in ("BUY", "SELL"):
                    self._log_entry_rejected(
                        "adx_ranging_filter",
                        symbol=symbol,
                        signal=signal,
                        event_id=event.event_id,
                        adx=adx,
                        adx_floor=adx_floor,
                        **diagnostics_base,
                    )
                    return

            if legacy_feature_gates and getattr(settings, "enforce_ema200_trend_filter", False):
                ema200 = features.get("ema_200")
                if ema200 is not None:
                    try:
                        ema200_f = float(ema200)
                        if signal in ("BUY", "STRONG_BUY") and entry_price < ema200_f:
                            self._log_entry_rejected(
                                "ema200_trend_filter",
                                symbol=symbol,
                                signal=signal,
                                event_id=event.event_id,
                                entry_price=entry_price,
                                ema200=ema200_f,
                                **diagnostics_base,
                            )
                            return
                        if signal in ("SELL", "STRONG_SELL") and entry_price > ema200_f:
                            self._log_entry_rejected(
                                "ema200_trend_filter",
                                symbol=symbol,
                                signal=signal,
                                event_id=event.event_id,
                                entry_price=entry_price,
                                ema200=ema200_f,
                                **diagnostics_base,
                            )
                            return
                    except (TypeError, ValueError):
                        pass

            # Feature gate: near upper Bollinger band = resistance — avoid chasing BUY
            if legacy_feature_gates and getattr(settings, "feature_filter_enabled", True) and signal in (
                "BUY",
                "STRONG_BUY",
            ):
                bb_pos = features.get("bb_position")
                if bb_pos is not None:
                    try:
                        bb_f = float(bb_pos)
                        cap = float(
                            getattr(settings, "block_buy_near_bb_upper_pct", 0.92)
                        )
                        if bb_f >= cap:
                            self._log_entry_rejected(
                                "near_resistance_bb",
                                symbol=symbol,
                                signal=signal,
                                event_id=event.event_id,
                                bb_position=bb_f,
                                threshold=cap,
                                **diagnostics_base,
                            )
                            return
                    except (TypeError, ValueError):
                        pass

            if legacy_feature_gates and getattr(settings, "sr_strength_filter_enabled", True):
                if signal in ("BUY", "STRONG_BUY"):
                    sr_at_res = features.get("sr_at_resistance")
                    if bool(sr_at_res):
                        self._log_entry_rejected(
                            "near_resistance_sr",
                            symbol=symbol,
                            signal=signal,
                            event_id=event.event_id,
                            sr_at_resistance=sr_at_res,
                            **diagnostics_base,
                        )
                        return
                    sr_res_strength = features.get("sr_resistance_strength")
                    if sr_res_strength is not None:
                        try:
                            sr_f = float(sr_res_strength)
                            sr_cap = float(
                                getattr(
                                    settings,
                                    "block_buy_min_sr_resistance_strength",
                                    0.7,
                                )
                            )
                            if sr_f >= sr_cap:
                                self._log_entry_rejected(
                                    "near_resistance_sr_strength",
                                    symbol=symbol,
                                    signal=signal,
                                    event_id=event.event_id,
                                    sr_resistance_strength=sr_f,
                                    threshold=sr_cap,
                                    **diagnostics_base,
                                )
                                return
                        except (TypeError, ValueError):
                            pass
                if signal in ("SELL", "STRONG_SELL"):
                    sr_at_sup = features.get("sr_at_support")
                    if bool(sr_at_sup):
                        self._log_entry_rejected(
                            "near_support_sr",
                            symbol=symbol,
                            signal=signal,
                            event_id=event.event_id,
                            sr_at_support=sr_at_sup,
                            **diagnostics_base,
                        )
                        return
                    sr_sup_strength = features.get("sr_support_strength")
                    if sr_sup_strength is not None:
                        try:
                            sr_f = float(sr_sup_strength)
                            sr_cap = float(
                                getattr(settings, "block_sell_min_sr_support_strength", 0.7)
                            )
                            if sr_f >= sr_cap:
                                self._log_entry_rejected(
                                    "near_support_sr_strength",
                                    symbol=symbol,
                                    signal=signal,
                                    event_id=event.event_id,
                                    sr_support_strength=sr_f,
                                    threshold=sr_cap,
                                    **diagnostics_base,
                                )
                                return
                        except (TypeError, ValueError):
                            pass

            if legacy_feature_gates and getattr(settings, "entry_signal_filter_enabled", True):
                filtered, filt_reason = self._entry_signal_filter.apply(signal, features)
                if filtered == "HOLD" and signal != "HOLD":
                    self._log_entry_rejected(
                        "entry_signal_filter",
                        symbol=symbol,
                        signal=signal,
                        event_id=event.event_id,
                        filter_reason=filt_reason,
                        entry_signal_filter_reason=filt_reason,
                        **diagnostics_base,
                    )
                    return
                signal = filtered

            # Clear opposite-side debounce so reversal can trade
            opp_key = self._debounce_key(symbol, "SELL" if side == "BUY" else "BUY")
            self._last_risk_approved.pop(opp_key, None)

            lots = entry_lots
            if lots < min_lot_size:
                logger.warning(
                    "trading_handler_zero_quantity",
                    symbol=symbol,
                    entry_price=entry_price,
                    lots=lots,
                    min_lot_size=min_lot_size,
                    contract_value_btc=cv,
                    event_id=event.event_id,
                )
                return

            quantity = float(lots)

            market_context = (
                (payload.get("reasoning_chain") or {}).get("market_context")
                if isinstance(payload.get("reasoning_chain"), dict)
                else {}
            )
            if not isinstance(market_context, dict):
                market_context = {}

            hold_floor_late = float(
                getattr(settings, "transformer_confidence_hold_floor", 0.0) or 0.0
            )
            if gates_on and transformer_gates:
                if float(confidence or 0.0) < hold_floor_late:
                    self._log_entry_rejected(
                        "low_confidence_reject",
                        symbol=symbol,
                        signal=signal,
                        event_id=event.event_id,
                        confidence=confidence,
                        threshold=hold_floor_late,
                        **diagnostics_base,
                    )
                    return
            elif gates_on:
                eff_min_conf = float(
                    getattr(settings, "transformer_min_confidence", None)
                    or getattr(settings, "min_confidence_threshold", 0.52)
                    or 0.52
                )
                if float(confidence or 0.0) < eff_min_conf:
                    self._log_entry_rejected(
                        "low_confidence_reject",
                        symbol=symbol,
                        signal=signal,
                        event_id=event.event_id,
                        confidence=confidence,
                        threshold=eff_min_conf,
                        **diagnostics_base,
                    )
                    return

            risk_payload = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": entry_price,
                "reference_price": entry_price,
                "risk_score": 0.8,
                "timestamp": datetime.now(timezone.utc),
                "decision_event_id": event.event_id,
                "reasoning_chain_id": (payload.get("reasoning_chain") or {}).get("chain_id"),
                "memory_context_id": payload.get("memory_context_id"),
                "agent_introspection_at_entry": payload.get("agent_introspection"),
                "confidence": confidence,
                "model_predictions": (payload.get("reasoning_chain") or {}).get("model_predictions"),
                "ml_signal_validated": True,
                "ml_signal_source": (
                    (market_context.get("decision_path") if isinstance(market_context, dict) else None)
                    or "transformer_agent_synthesis"
                ),
                "ml_evidence_id": (
                    (payload.get("ml_evidence_snapshot") or {}).get("evidence_id")
                    if isinstance(payload.get("ml_evidence_snapshot"), dict)
                    else None
                ),
                "policy_verdict": payload.get("policy_verdict"),
                "market_context": market_context,
                "usd_inr_rate": usdinr_rate,
                "required_margin_inr": required_margin_inr,
                "available_cash_inr": available_cash_inr,
                "portfolio_value_inr": portfolio_value_inr,
                "entry_lots": entry_lots,
                "contract_value_btc": cv,
                "tick_size": tick_sz,
                "product_id": specs.product_id,
                "leverage": leverage,
                "entry_portfolio_margin_fraction": entry_portfolio_frac,
                "margin_inr_budget": margin_inr,
            }
            if signal_path_diag:
                risk_payload["signal_path_diagnostics"] = signal_path_diag
            atr_out = features.get("atr_14")
            if atr_out is not None:
                try:
                    risk_payload["atr_14"] = float(atr_out)
                except (TypeError, ValueError):
                    pass
            if stop_loss_price is not None and take_profit_price is not None:
                risk_payload["stop_loss"] = stop_loss_price
                risk_payload["take_profit"] = take_profit_price
            v43_bar = mc.get("v43_closed_bar_index") if isinstance(mc, dict) else None
            if v43_bar is not None:
                try:
                    risk_payload["v43_closed_bar_index"] = int(v43_bar)
                except (TypeError, ValueError):
                    pass
            risk_approved = RiskApprovedEvent(
                source="trading_handler",
                correlation_id=event.event_id,
                payload=risk_payload,
            )
            await event_bus.publish(risk_approved)
            self._last_trade_wall_time = time.time()
            if legacy_feature_gates and getattr(settings, "entry_signal_filter_enabled", True):
                self._entry_signal_filter.record_trade()

            # ai_signal_minimal_entry_gates already in diagnostics_base — do not pass twice (structlog TypeError).
            logger.info(
                "trading_handler_risk_approved_published",
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                entry_lots=entry_lots,
                leverage=leverage,
                margin_inr=margin_inr,
                entry_portfolio_margin_fraction=entry_portfolio_frac,
                portfolio_value_inr=portfolio_value_inr,
                available_cash_inr=available_cash_inr,
                event_id=event.event_id,
                **diagnostics_base,
            )
            try:
                from agent.core.signal_audit_md import append_risk_approved

                append_risk_approved(
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    entry_price=entry_price,
                    event_id=event.event_id,
                    reasoning_chain_id=(payload.get("reasoning_chain") or {}).get("chain_id")
                    if isinstance(payload.get("reasoning_chain"), dict)
                    else None,
                )
            except Exception as e:
                logger.warning(
                    "signal_audit_risk_approved_append_failed",
                    symbol=symbol,
                    error=str(e),
                )

        except Exception as e:
            logger.error(
                "trading_handler_decision_ready_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True,
            )

    async def _try_ml_reversal_exit_while_policy_hold(
        self,
        *,
        symbol: str,
        event_id: str,
        reasoning_chain: Dict[str, Any],
        diagnostics_base: Dict[str, Any],
    ) -> bool:
        """Close open position when gated ML contradicts side but policy emitted HOLD."""
        if not bool(getattr(settings, "position_exit_on_ml_reversal_enabled", True)):
            return False
        if not self.execution_module:
            return False

        min_conf = float(
            getattr(settings, "position_exit_ml_confidence_min", 0.70) or 0.70
        )
        mc = (
            reasoning_chain.get("market_context", {})
            if isinstance(reasoning_chain.get("market_context"), dict)
            else {}
        )
        ml_val = mc.get("ml_validation") if isinstance(mc.get("ml_validation"), dict) else {}
        v43_dec = (
            mc.get("v43_dedicated_decision")
            if isinstance(mc.get("v43_dedicated_decision"), dict)
            else {}
        )
        ml_conf = float(
            ml_val.get("model_confidence")
            or v43_dec.get("confidence")
            or mc.get("consensus_confidence")
            or 0.0
        )
        if ml_conf > 1.0:
            ml_conf = ml_conf / 100.0
        if ml_conf < min_conf:
            return False

        final_short = bool(ml_val.get("final_short"))
        final_long = bool(ml_val.get("final_long"))
        short_enabled = bool(
            getattr(settings, "jacksparrow_v43_short_execution_enabled", False)
        )

        open_pos = self.execution_module.position_manager.get_position(symbol)
        if (
            bool(getattr(settings, "exchange_position_reconcile_enabled", True))
            and (not open_pos or open_pos.get("status") != "open")
        ):
            try:
                from agent.core.mcp_orchestrator import _exchange_has_open_position_async
                from agent.core.position_reconcile import reconcile_positions_with_exchange

                if await _exchange_has_open_position_async(symbol):
                    await reconcile_positions_with_exchange(self.execution_module)
                    open_pos = self.execution_module.position_manager.get_position(symbol)
            except Exception as e:
                logger.warning(
                    "ml_reversal_reconcile_failed",
                    symbol=symbol,
                    error=str(e),
                )

        if not open_pos or open_pos.get("status") != "open":
            return False

        pos_side = open_pos.get("side", "")
        should_close = (pos_side == "long" and final_short) or (
            pos_side == "short" and final_long and short_enabled
        )
        if not should_close:
            return False

        logger.info(
            "ml_reversal_while_policy_hold",
            symbol=symbol,
            pos_side=pos_side,
            final_short=final_short,
            final_long=final_long,
            ml_confidence=ml_conf,
            event_id=event_id,
        )
        close_result = await self.execution_module.close_position(
            symbol, exit_reason="ml_reversal_while_policy_hold"
        )
        if not close_result.success:
            logger.warning(
                "ml_reversal_while_policy_hold_failed",
                symbol=symbol,
                event_id=event_id,
                **diagnostics_base,
            )
            return False
        return True

    async def _get_current_price(self, symbol: str, state: Optional[Any]) -> Optional[float]:
        """Get current price from context or live ticker. Returns None if unavailable."""
        try:
            if state and hasattr(state, "config") and state.config:
                market_data = state.config.get("market_data", {})
                if isinstance(market_data, dict) and market_data.get("price"):
                    return float(market_data["price"])
            if state and hasattr(state, "market_data") and state.market_data:
                md = state.market_data
                if isinstance(md, dict) and md.get("price"):
                    return float(md["price"])
        except (TypeError, ValueError):
            pass
        if self.delta_client:
            try:
                ticker = await self.delta_client.get_ticker(symbol)
                result = ticker.get("result") or ticker
                if isinstance(result, dict):
                    close = result.get("close") or result.get("mark_price")
                    if close is not None:
                        return float(close)
            except Exception as e:
                logger.debug(
                    "trading_handler_ticker_failed",
                    symbol=symbol,
                    error=str(e),
                )
        return None

    async def _get_usdinr_rate(self, state: Optional[Any]) -> float:
        """Best-effort USDINR lookup: context -> Redis cached last-good -> config fallback."""
        from agent.core.fx_rate import resolve_usdinr_rate

        md = None
        try:
            if state and hasattr(state, "config") and isinstance(state.config, dict):
                md = state.config.get("market_data")
        except Exception as e:
            logger.debug("usdinr_context_lookup_failed", error=str(e))
        return await resolve_usdinr_rate(state_market_data=md if isinstance(md, dict) else None)

    async def _get_portfolio_value_inr(
        self,
        state: Optional[Any],
        symbol: str,
        *,
        available_cash_inr: Optional[float] = None,
    ) -> float:
        """Portfolio value in INR for lot sizing, capped by live wallet when known."""
        book_inr: Optional[float] = None
        if self.risk_manager and getattr(self.risk_manager, "portfolio", None):
            try:
                usdinr = await self._get_usdinr_rate(state)
                total_usd = float(self.risk_manager.portfolio.total_value)
                if total_usd > 0 and usdinr > 0:
                    book_inr = total_usd * usdinr
            except (TypeError, ValueError):
                pass
        if book_inr is None and state is not None and hasattr(state, "portfolio_value"):
            try:
                val = float(state.portfolio_value)
                if val > 0:
                    book_inr = val
            except (TypeError, ValueError):
                pass
        if book_inr is None:
            book_inr = float(getattr(settings, "initial_balance", 20000.0) or 20000.0)
        # Live wallet is the sizing base for 60/40 margin+reserve (must match risk reserve check).
        if available_cash_inr is not None and float(available_cash_inr) > 0:
            return float(available_cash_inr)
        return book_inr

    async def _get_available_cash_inr(self, state: Optional[Any], symbol: str) -> float:
        """INR cash from live exchange wallet when available, else agent state."""
        if self.execution_module:
            try:
                snapshot = await asyncio.wait_for(
                    self.execution_module.get_exchange_portfolio_snapshot(symbol=symbol),
                    timeout=5.0,
                )
                live_inr = self._extract_available_inr_from_snapshot(snapshot)
                if live_inr > 0:
                    return live_inr
            except Exception as exc:
                logger.debug(
                    "live_wallet_balance_unavailable",
                    symbol=symbol,
                    error=str(exc),
                )
        if state is not None and hasattr(state, "cash_balance"):
            try:
                val = float(state.cash_balance)
                if val > 0:
                    return val
            except Exception as e:
                logger.debug("cash_balance_parse_failed", error=str(e))
        if state is not None and hasattr(state, "portfolio_value"):
            try:
                val = float(state.portfolio_value)
                if val > 0:
                    return val
            except Exception as e:
                logger.debug("portfolio_value_parse_failed", error=str(e))
        return float(getattr(settings, "initial_balance", 20000.0) or 20000.0)

    @staticmethod
    def _extract_available_inr_from_snapshot(snapshot: Dict[str, Any]) -> float:
        """Parse wallet balances from exchange portfolio snapshot into INR."""
        wallet = snapshot.get("wallet_balances") if isinstance(snapshot, dict) else None
        if not isinstance(wallet, dict):
            return 0.0
        rows = wallet.get("result")
        if isinstance(rows, dict):
            rows = rows.get("balances") or [rows]
        if not isinstance(rows, list):
            return 0.0
        total_usd = 0.0
        for row in rows:
            if not isinstance(row, dict):
                continue
            asset = str(row.get("asset_symbol") or row.get("currency") or "").upper()
            raw_bal = row.get("available_balance")
            if raw_bal is None:
                raw_bal = row.get("balance")
            try:
                val = float(raw_bal)
            except (TypeError, ValueError):
                continue
            if val <= 0:
                continue
            if asset == "INR":
                return val
            if asset in ("USD", "USDT", "USDC"):
                total_usd += val
        if total_usd > 0:
            rate = float(getattr(settings, "usdinr_fallback_rate", 83.0) or 83.0)
            return total_usd * rate
        return 0.0

    async def register_handlers(self):
        """Register event handlers with event bus."""
        event_bus.subscribe(
            EventType.DECISION_READY,
            self.handle_decision_ready_for_trading,
        )
        logger.info("trading_handlers_registered")
