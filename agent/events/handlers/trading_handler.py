"""
Trading event handler.

Bridges DecisionReadyEvent to RiskApprovedEvent by performing risk validation
and publishing RiskApprovedEvent when trades are approved.
"""

from typing import Any, Dict, Optional
from datetime import datetime, timezone
import structlog
import time

from agent.events.schemas import DecisionReadyEvent, RiskApprovedEvent, EventType
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager
from agent.core.config import settings
from agent.core.futures_utils import margin_required_inr
from agent.core.v15_signal import apply_v15_entry_gate
from agent.core.learning_system import LearningSystem
from agent.core.signal_filter import EntrySignalFilter
from agent.core.redis_config import get_cache
from agent.learning.dynamic_thresholds import (
    get_effective_min_confidence_threshold,
    resolve_metadata_recommended_threshold,
)

logger = structlog.get_logger()

# Defaults live in config (`Settings.trade_signal_debounce_seconds`,
# `Settings.min_risk_reward_ratio`, `Settings.adx_ranging_threshold`).
DEFAULT_TRADE_SIGNAL_DEBOUNCE_SECONDS = 10
DEFAULT_MIN_RISK_REWARD_RATIO = 1.2
DEFAULT_ADX_RANGING_THRESHOLD = 20.0


class TradingEventHandler:
    """Handler that bridges DecisionReadyEvent to RiskApprovedEvent."""

    def __init__(self, risk_manager, delta_client=None, execution_module=None):
        """Initialize trading event handler.

        Args:
            risk_manager: RiskManager instance for trade validation
            delta_client: DeltaExchangeClient for fetching live market prices (required for paper trading)
            execution_module: ExecutionEngine instance for position checks and signal-reversal exit
        """
        self.risk_manager = risk_manager
        self.context_manager = context_manager
        self.delta_client = delta_client
        self.execution_module = execution_module
        self.learning_system = LearningSystem()
        # Deduplicate: last (symbol, side) -> timestamp of last RiskApproved published
        self._last_risk_approved: Dict[str, float] = {}
        self._entry_signal_filter = EntrySignalFilter(
            max_trades_per_hour=int(getattr(settings, "max_trades_per_hour", 0) or 0),
            min_breakout_score=float(getattr(settings, "entry_min_breakout_score", 0.0) or 0.0),
        )

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
            or DEFAULT_TRADE_SIGNAL_DEBOUNCE_SECONDS
        )
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
                    out["calibration_step6_confidence"] = s.get("confidence")
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
            entry_proba_summary = self._summarize_model_entry_proba(model_predictions)
            diagnostics_base: Dict[str, Any] = {
                "hour_bucket_utc": hour_bucket_utc,
                **entry_proba_summary,
                **self._reasoning_pipeline_diagnostics(
                    reasoning_chain if isinstance(reasoning_chain, dict) else {}
                ),
            }
            raw_confidence = confidence
            confidence = await self.learning_system.calibrate_runtime_confidence(
                confidence, model_predictions
            )
            diagnostics_base["raw_confidence"] = raw_confidence
            diagnostics_base["calibrated_confidence"] = confidence

            # Skip HOLD - no trade to execute
            if signal == "HOLD" or not signal:
                self._log_entry_rejected(
                    "hold_at_synthesis",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    **diagnostics_base,
                )
                return

            # Signal expiry: reject stale signals
            ts = payload.get("timestamp")
            if ts is not None:
                try:
                    if hasattr(ts, "timestamp"):
                        ts_sec = ts.timestamp()
                    elif isinstance(ts, (int, float)):
                        ts_sec = float(ts)
                    else:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if isinstance(ts, str) else ts
                        ts_sec = dt.timestamp() if hasattr(dt, "timestamp") else 0
                    age = time.time() - ts_sec
                    if age > getattr(settings, "max_signal_age_seconds", 10):
                        self._log_entry_rejected(
                            "stale_signal_reject",
                            symbol=symbol,
                            signal=signal,
                            event_id=event.event_id,
                            age_seconds=round(age, 3),
                            max_signal_age_seconds=getattr(settings, "max_signal_age_seconds", 10),
                            **diagnostics_base,
                        )
                        return
                except Exception:
                    pass

            v15_diag: Dict[str, Any] = {}
            new_signal, v15_diag = apply_v15_entry_gate(signal, model_predictions, features)
            if new_signal == "HOLD" and signal not in ("HOLD", None, ""):
                self._log_entry_rejected(
                    "v15_entry_gate",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    **diagnostics_base,
                    **v15_diag,
                )
                return
            signal = new_signal
            if signal in ("BUY", "STRONG_BUY"):
                side = "BUY"
                risk_side = "long"
            elif signal in ("SELL", "STRONG_SELL"):
                side = "SELL"
                risk_side = "short"
            else:
                self._log_entry_rejected(
                    "v15_gate_hold",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    **diagnostics_base,
                )
                return

            # Signal-reversal exit: if open position contradicts signal, close first and return
            if self.execution_module:
                open_pos = self.execution_module.position_manager.get_position(symbol)
                if open_pos and open_pos.get("status") == "open":
                    pos_side = open_pos.get("side", "")
                    if (pos_side == "long" and signal in ("STRONG_SELL", "SELL")) or (
                        pos_side == "short" and signal in ("STRONG_BUY", "BUY")
                    ):
                        mh = open_pos.get("v15_min_hold_until")
                        if mh is not None:
                            now = datetime.now(timezone.utc)
                            if isinstance(mh, datetime):
                                mhu = mh if mh.tzinfo else mh.replace(tzinfo=timezone.utc)
                                if now < mhu:
                                    self._log_entry_rejected(
                                        "v15_min_hold_blocks_reversal",
                                        symbol=symbol,
                                        signal=signal,
                                        event_id=event.event_id,
                                        min_hold_until=mhu.isoformat(),
                                        **diagnostics_base,
                                    )
                                    return
                        logger.info(
                            "signal_reversal_exit",
                            symbol=symbol,
                            pos=pos_side,
                            signal=signal,
                            event_id=event.event_id,
                        )
                        await self.execution_module.close_position(symbol, exit_reason="signal_reversal")
                        return

            # Check confidence threshold (Redis learning layer may nudge within bounds)
            eff_min_conf = await get_effective_min_confidence_threshold()
            rec_threshold = resolve_metadata_recommended_threshold(
                signal=signal,
                model_predictions=model_predictions,
            )
            # Optional temporary validation mode for paper-trading pipeline checks.
            if bool(getattr(settings, "paper_trade_validation_mode", False)):
                eff_min_conf = float(
                    getattr(settings, "paper_trade_validation_min_confidence", 0.45) or 0.45
                )
            elif rec_threshold is not None:
                # Choose a conservative midpoint between global threshold and metadata recommendation.
                eff_min_conf = max(0.0, min(1.0, (eff_min_conf + rec_threshold) / 2.0))
            if confidence < eff_min_conf:
                self._log_entry_rejected(
                    "low_confidence_reject",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    confidence=confidence,
                    threshold=eff_min_conf,
                    metadata_recommended_threshold=rec_threshold,
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

            is_v15_pred = any(
                (p.get("context") or {}).get("format") == "v15_pipeline"
                for p in model_predictions
                if isinstance(p, dict)
            )
            vol = features.get("volatility")
            if vol is None and not is_v15_pred:
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
                if not is_v15_pred:
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
            if min_vol > 0 and not is_v15_pred:
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
                except Exception:
                    pass
            min_atr_pct = float(getattr(settings, "entry_min_atr_pct_of_price", 0.0) or 0.0)
            if min_atr_pct > 0 and entry_price > 0:
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
            # Always enforce exchange minimum lots; fixed lot can only increase from this floor.
            fixed_lots = max(min_lot_size, fixed_lots)
            leverage = int(getattr(settings, "isolated_margin_leverage", 5) or 5)
            usdinr_rate = await self._get_usdinr_rate(state)
            required_margin_inr = margin_required_inr(
                lots=fixed_lots,
                btc_price_usd=entry_price,
                usdinr_rate=usdinr_rate,
                leverage=leverage,
                contract_value_btc=float(getattr(settings, "contract_value_btc", 0.001)),
            )
            available_cash_inr = self._get_available_cash_inr(state)
            if required_margin_inr <= 0 or available_cash_inr < required_margin_inr:
                self._log_entry_rejected(
                    "insufficient_margin_inr",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    available_cash_inr=available_cash_inr,
                    required_margin_inr=required_margin_inr,
                    usdinr_rate=usdinr_rate,
                    leverage=leverage,
                    fixed_lots=fixed_lots,
                    **diagnostics_base,
                )
                return

            proposed_size = max(0.01, min(required_margin_inr / max(available_cash_inr, 1.0), settings.max_position_size))

            # Validate trade with risk manager
            validation = await self.risk_manager.validate_trade(
                symbol=symbol,
                side=risk_side,
                proposed_size=proposed_size,
                entry_price=entry_price,
                stop_loss=None,  # Execution will compute from config
            )

            if not validation.get("approved", False):
                self._log_entry_rejected(
                    "risk_rejected",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
                    side=side,
                    risk_reason=validation.get("reason", "Unknown"),
                    **diagnostics_base,
                )
                return

            # Deduplicate: one RiskApproved per (symbol, side) per time window
            if self._should_skip_debounce(symbol, side):
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
                        or DEFAULT_TRADE_SIGNAL_DEBOUNCE_SECONDS
                    ),
                    **diagnostics_base,
                )
                return

            # ATR-scaled SL/TP (optional): distance = max(config %, atr_14 * mult)
            atr = features.get("atr_14")
            use_atr_sl_tp = bool(getattr(settings, "use_atr_scaled_sl_tp", False))
            stop_loss_price = None
            take_profit_price = None
            stop_pct = settings.stop_loss_percentage
            take_pct = settings.take_profit_percentage
            if use_atr_sl_tp and atr is not None:
                try:
                    atr_f = float(atr)
                    sl_mult = float(getattr(settings, "atr_sl_distance_mult", 1.0))
                    tp_mult = float(getattr(settings, "atr_tp_distance_mult", 1.5))
                    sl_dist = max(entry_price * stop_pct, atr_f * sl_mult)
                    tp_dist = max(entry_price * take_pct, atr_f * tp_mult)
                    if side == "BUY":
                        stop_loss_price = entry_price - sl_dist
                        take_profit_price = entry_price + tp_dist
                    else:
                        stop_loss_price = entry_price + sl_dist
                        take_profit_price = entry_price - tp_dist
                except (TypeError, ValueError):
                    use_atr_sl_tp = False
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
            elif not use_atr_sl_tp or stop_loss_price is None:
                stop_loss_price = None
                take_profit_price = None
                stop_pct = settings.stop_loss_percentage
                take_pct = settings.take_profit_percentage
                if not self._check_entry_profit_potential(entry_price, side, stop_pct, take_pct):
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

            # Multi-timeframe confirmation: block BUY if 15m trend bearish, SELL if 15m trend bullish
            if getattr(settings, "mtf_confirmation_enabled", False):
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

            # ADX ranging market filter: block mild BUY/SELL in very low trend strength
            if not is_v15_pred:
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

            # EMA200 regime filter for trend conformity
            if getattr(settings, "enforce_ema200_trend_filter", False):
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
            if getattr(settings, "feature_filter_enabled", True) and signal in (
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

            if getattr(settings, "sr_strength_filter_enabled", True):
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

            if getattr(settings, "entry_signal_filter_enabled", True):
                filtered, filt_reason = self._entry_signal_filter.apply(signal, features)
                if filtered == "HOLD" and signal != "HOLD":
                    self._log_entry_rejected(
                        "entry_signal_filter",
                        symbol=symbol,
                        signal=signal,
                        event_id=event.event_id,
                        filter_reason=filt_reason,
                        **diagnostics_base,
                    )
                    return
                signal = filtered

            # Clear opposite-side debounce so reversal can trade
            opp_key = self._debounce_key(symbol, "SELL" if side == "BUY" else "BUY")
            self._last_risk_approved.pop(opp_key, None)

            lots = fixed_lots
            if lots < min_lot_size:
                logger.warning(
                    "trading_handler_zero_quantity",
                    symbol=symbol,
                    entry_price=entry_price,
                    lots=lots,
                    min_lot_size=min_lot_size,
                    contract_value_btc=float(getattr(settings, "contract_value_btc", 0.001)),
                    event_id=event.event_id,
                )
                return

            quantity = float(lots)

            # Publish RiskApprovedEvent to trigger execution
            risk_payload = {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": entry_price,
                "risk_score": 0.8,
                "timestamp": datetime.now(timezone.utc),
                "reasoning_chain_id": (payload.get("reasoning_chain") or {}).get("chain_id"),
                "confidence": confidence,
                "model_predictions": (payload.get("reasoning_chain") or {}).get("model_predictions"),
                "usd_inr_rate": usdinr_rate,
                "required_margin_inr": required_margin_inr,
                "available_cash_inr": available_cash_inr,
            }
            if v15_diag:
                risk_payload["v15_diagnostics"] = v15_diag
            if stop_loss_price is not None and take_profit_price is not None:
                risk_payload["stop_loss"] = stop_loss_price
                risk_payload["take_profit"] = take_profit_price
            risk_approved = RiskApprovedEvent(
                source="trading_handler",
                correlation_id=event.event_id,
                payload=risk_payload,
            )
            await event_bus.publish(risk_approved)
            if getattr(settings, "entry_signal_filter_enabled", True):
                self._entry_signal_filter.record_trade()

            logger.info(
                "trading_handler_risk_approved_published",
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                event_id=event.event_id,
                **diagnostics_base,
            )

        except Exception as e:
            logger.error(
                "trading_handler_decision_ready_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True,
            )

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
        try:
            if state and hasattr(state, "config") and isinstance(state.config, dict):
                md = state.config.get("market_data", {})
                if isinstance(md, dict):
                    for key in ("usd_inr", "usd_inr_rate", "usdinr", "inr_per_usd"):
                        val = md.get(key)
                        if val is not None and float(val) > 0:
                            return float(val)
        except Exception:
            pass
        try:
            cached = await get_cache("fx:usdinr:last")
            if isinstance(cached, dict):
                val = cached.get("rate")
                if val is not None and float(val) > 0:
                    return float(val)
        except Exception:
            pass
        return float(getattr(settings, "usdinr_fallback_rate", 83.0) or 83.0)

    def _get_available_cash_inr(self, state: Optional[Any]) -> float:
        """Best-effort INR cash extraction from runtime state."""
        if state is not None and hasattr(state, "portfolio_value"):
            try:
                val = float(state.portfolio_value)
                if val > 0:
                    return val
            except Exception:
                pass
        return float(getattr(settings, "initial_balance", 20000.0) or 20000.0)

    async def register_handlers(self):
        """Register event handlers with event bus."""
        event_bus.subscribe(
            EventType.DECISION_READY,
            self.handle_decision_ready_for_trading,
        )
        logger.info("trading_handlers_registered")
