"""
Trading event handler.

Bridges DecisionReadyEvent to RiskApprovedEvent by performing risk validation
and publishing RiskApprovedEvent when trades are approved.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import structlog
import time

from agent.events.schemas import DecisionReadyEvent, RiskApprovedEvent, EventType
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager
from agent.core.config import settings

logger = structlog.get_logger()

# Debounce: one RiskApproved per (symbol, side) within this many seconds
TRADE_SIGNAL_DEBOUNCE_SECONDS = 30
# Minimum risk/reward ratio (reward/risk) to allow entry (e.g. 1.5 = take_profit distance >= 1.5 * stop_loss distance)
MIN_RISK_REWARD_RATIO = 1.2


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
        # Deduplicate: last (symbol, side) -> timestamp of last RiskApproved published
        self._last_risk_approved: Dict[str, float] = {}

    def _debounce_key(self, symbol: str, side: str) -> str:
        """Key for debounce: same symbol+side within window = duplicate."""
        return f"{symbol}:{side}"

    def _should_skip_debounce(self, symbol: str, side: str) -> bool:
        """True if we should skip publishing (duplicate within window)."""
        key = self._debounce_key(symbol, side)
        now = time.time()
        last = self._last_risk_approved.get(key, 0)
        if now - last < TRADE_SIGNAL_DEBOUNCE_SECONDS:
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
        return ratio >= MIN_RISK_REWARD_RATIO

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

            # Skip HOLD - no trade to execute
            if signal == "HOLD" or not signal:
                logger.debug(
                    "trading_handler_skipping_hold",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
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
                        from datetime import datetime
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")) if isinstance(ts, str) else ts
                        ts_sec = dt.timestamp() if hasattr(dt, "timestamp") else 0
                    age = time.time() - ts_sec
                    if age > getattr(settings, "max_signal_age_seconds", 10):
                        logger.warning("signal_expired", age=age, symbol=symbol, event_id=event.event_id)
                        return
                except Exception:
                    pass

            # Map signal to side (BUY/SELL for event, long/short for risk manager)
            if signal in ("BUY", "STRONG_BUY"):
                side = "BUY"
                risk_side = "long"
            elif signal in ("SELL", "STRONG_SELL"):
                side = "SELL"
                risk_side = "short"
            else:
                logger.debug(
                    "trading_handler_skipping_non_trade_signal",
                    symbol=symbol,
                    signal=signal,
                    event_id=event.event_id,
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
                        logger.info(
                            "signal_reversal_exit",
                            symbol=symbol,
                            pos=pos_side,
                            signal=signal,
                            event_id=event.event_id,
                        )
                        await self.execution_module.close_position(symbol, exit_reason="signal_reversal")
                        return

            # Check confidence threshold
            if confidence < settings.min_confidence_threshold:
                logger.info(
                    "trading_handler_confidence_below_threshold",
                    symbol=symbol,
                    signal=signal,
                    confidence=confidence,
                    threshold=settings.min_confidence_threshold,
                    event_id=event.event_id,
                )
                return

            # Get portfolio value and current price from live market data
            state = self.context_manager.get_state()
            portfolio_value = (
                state.portfolio_value if state else settings.initial_balance
            )
            entry_price = await self._get_current_price(symbol, state)
            if entry_price is None or entry_price <= 0:
                logger.warning(
                    "trading_handler_no_price_available",
                    symbol=symbol,
                    event_id=event.event_id,
                    message="Skipping trade: no valid market price available",
                )
                return

            features = (payload.get("reasoning_chain") or {}).get("market_context", {}).get("features", {})
            vol = features.get("volatility")
            if vol is None:
                logger.warning(
                    "trading_handler_missing_volatility",
                    symbol=symbol,
                    event_id=event.event_id,
                    message="Volatility required for Kelly sizing; skipping trade",
                )
                return
            strength_map = {"STRONG_BUY": 0.9, "BUY": 0.65, "STRONG_SELL": 0.9, "SELL": 0.65}
            regime = "high" if vol > 5 else "medium" if vol > 2.5 else "low"
            rr_ratio = (
                settings.take_profit_percentage / settings.stop_loss_percentage
                if settings.stop_loss_percentage
                else 2.0
            )
            position_size = self.risk_manager.calculate_position_size(
                signal_strength=strength_map.get(signal, 0.65),
                volatility_regime=regime,
                win_probability=0.52 + confidence * 0.1,
                risk_reward_ratio=rr_ratio,
            )
            proposed_size = max(0.01, min(position_size, settings.max_position_size))

            # Validate trade with risk manager
            validation = await self.risk_manager.validate_trade(
                symbol=symbol,
                side=risk_side,
                proposed_size=proposed_size,
                entry_price=entry_price,
                stop_loss=None,  # Execution will compute from config
            )

            if not validation.get("approved", False):
                logger.info(
                    "trading_handler_risk_rejected",
                    symbol=symbol,
                    side=side,
                    reason=validation.get("reason", "Unknown"),
                    event_id=event.event_id,
                )
                return

            # Deduplicate: one RiskApproved per (symbol, side) per time window
            if self._should_skip_debounce(symbol, side):
                logger.info(
                    "trading_handler_debounce_skip",
                    symbol=symbol,
                    side=side,
                    event_id=event.event_id,
                    message="Skipping duplicate RiskApproved within signal window",
                )
                return

            # ATR-based SL/TP when available; else use config and profit gate
            atr = features.get("atr_14")
            use_atr_sl_tp = atr is not None and atr > 0 and entry_price > 0
            stop_loss_price = None
            take_profit_price = None
            if use_atr_sl_tp:
                sl_dist = 1.5 * atr
                tp_dist = 3.0 * atr
                if side == "BUY":
                    stop_loss_price = entry_price - sl_dist
                    take_profit_price = entry_price + tp_dist
                else:
                    stop_loss_price = entry_price + sl_dist
                    take_profit_price = entry_price - tp_dist
            else:
                stop_pct = settings.stop_loss_percentage
                take_pct = settings.take_profit_percentage
                if not self._check_entry_profit_potential(entry_price, side, stop_pct, take_pct):
                    logger.info(
                        "trading_handler_profit_gate_rejected",
                        symbol=symbol,
                        side=side,
                        entry_price=entry_price,
                        min_ratio=MIN_RISK_REWARD_RATIO,
                        event_id=event.event_id,
                        message="Skipping trade: risk/reward below minimum",
                    )
                    return

            # Multi-timeframe confirmation: block BUY if 15m trend bearish, SELL if 15m trend bullish
            if getattr(settings, "mtf_confirmation_enabled", False):
                trend_15m = features.get("trend_15m")
                if trend_15m is not None:
                    if signal in ("BUY", "STRONG_BUY") and trend_15m < 0:
                        logger.info(
                            "mtf_filter_blocked",
                            symbol=symbol,
                            signal=signal,
                            trend_15m=trend_15m,
                            event_id=event.event_id,
                        )
                        return
                    if signal in ("SELL", "STRONG_SELL") and trend_15m > 0:
                        logger.info(
                            "mtf_filter_blocked",
                            symbol=symbol,
                            signal=signal,
                            trend_15m=trend_15m,
                            event_id=event.event_id,
                        )
                        return

            # ADX ranging market filter: block mild BUY/SELL in low trend strength
            adx = features.get("adx_14")
            if adx is not None and adx < 20 and signal in ("BUY", "SELL"):
                logger.info(
                    "entry_blocked_ranging_market",
                    adx=adx,
                    signal=signal,
                    symbol=symbol,
                    event_id=event.event_id,
                )
                return

            # Clear opposite-side debounce so reversal can trade
            opp_key = self._debounce_key(symbol, "SELL" if side == "BUY" else "BUY")
            self._last_risk_approved.pop(opp_key, None)

            adjusted_size = validation.get("adjusted_size", proposed_size)
            quantity_dollars = adjusted_size * portfolio_value
            quantity = quantity_dollars / entry_price if entry_price > 0 else 0

            if quantity <= 0:
                logger.warning(
                    "trading_handler_zero_quantity",
                    symbol=symbol,
                    entry_price=entry_price,
                    quantity_dollars=quantity_dollars,
                    event_id=event.event_id,
                )
                return

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
            }
            if stop_loss_price is not None and take_profit_price is not None:
                risk_payload["stop_loss"] = stop_loss_price
                risk_payload["take_profit"] = take_profit_price
            risk_approved = RiskApprovedEvent(
                source="trading_handler",
                correlation_id=event.event_id,
                payload=risk_payload,
            )
            await event_bus.publish(risk_approved)

            logger.info(
                "trading_handler_risk_approved_published",
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                event_id=event.event_id,
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

    async def register_handlers(self):
        """Register event handlers with event bus."""
        event_bus.subscribe(
            EventType.DECISION_READY,
            self.handle_decision_ready_for_trading,
        )
        logger.info("trading_handlers_registered")
