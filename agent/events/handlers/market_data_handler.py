"""
Market data event handler.

Handles market data events and triggers feature computation.
"""

from typing import Dict, Any
import structlog

from agent.events.schemas import (
    MarketTickEvent,
    CandleClosedEvent,
    PriceFluctuationEvent,
    FeatureRequestEvent,
    EventType
)
from agent.events.event_bus import event_bus
from agent.core.context_manager import context_manager

logger = structlog.get_logger()


class MarketDataEventHandler:
    """Handler for market data events."""
    
    def __init__(self):
        """Initialize market data event handler."""
        self.context_manager = context_manager
    
    async def handle_market_tick(self, event: MarketTickEvent):
        """Handle market tick event.
        
        Args:
            event: Market tick event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            price = payload.get("price")
            volume = payload.get("volume")
            
            # Update context with latest price
            self.context_manager.update_context({
                "market_data": {
                    "symbol": symbol,
                    "price": price,
                    "volume": volume,
                    "timestamp": payload.get("timestamp")
                }
            })
            
            logger.debug(
                "market_tick_handled",
                symbol=symbol,
                price=price,
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "market_tick_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )
    
    async def handle_candle_closed(self, event: CandleClosedEvent):
        """Handle candle closed event.
        
        Args:
            event: Candle closed event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            interval = payload.get("interval")
            
            # Update context with candle data
            self.context_manager.update_context({
                "market_data": {
                    "symbol": symbol,
                    "interval": interval,
                    "open": payload.get("open"),
                    "high": payload.get("high"),
                    "low": payload.get("low"),
                    "close": payload.get("close"),
                    "volume": payload.get("volume"),
                    "timestamp": payload.get("timestamp")
                }
            })
            
            # Trigger feature computation - Request all 50 features required by ML models
            # This matches the FEATURE_LIST from training scripts and mcp_orchestrator
            feature_request = FeatureRequestEvent(
                source="market_data_handler",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "feature_names": [
                        # Price-based (16 features)
                        'sma_10', 'sma_20', 'sma_50', 'sma_100', 'sma_200',
                        'ema_12', 'ema_26', 'ema_50',
                        'close_sma_20_ratio', 'close_sma_50_ratio', 'close_sma_200_ratio',
                        'high_low_spread', 'close_open_ratio', 'body_size', 'upper_shadow', 'lower_shadow',
                        # Momentum (10 features)
                        'rsi_14', 'rsi_7', 'stochastic_k_14', 'stochastic_d_14',
                        'williams_r_14', 'cci_20', 'roc_10', 'roc_20',
                        'momentum_10', 'momentum_20',
                        # Trend (8 features)
                        'macd', 'macd_signal', 'macd_histogram',
                        'adx_14', 'aroon_up', 'aroon_down', 'aroon_oscillator',
                        'trend_strength',
                        # Volatility (8 features)
                        'bb_upper', 'bb_lower', 'bb_width', 'bb_position',
                        'atr_14', 'atr_20',
                        'volatility_10', 'volatility_20',
                        # Volume (6 features)
                        'volume_sma_20', 'volume_ratio', 'obv',
                        'volume_price_trend', 'accumulation_distribution', 'chaikin_oscillator',
                        # Returns (2 features)
                        'returns_1h', 'returns_24h'
                    ],
                    "timestamp": payload.get("timestamp"),
                    "version": "latest"
                }
            )
            
            await event_bus.publish(feature_request)
            
            logger.info(
                "candle_closed_handled",
                symbol=symbol,
                interval=interval,
                candle_timestamp=payload.get("timestamp"),
                close_price=payload.get("close"),
                message="Candle closed - triggering decision generation pipeline (features -> models -> reasoning -> decision)",
                event_id=event.event_id,
                feature_request_id=feature_request.event_id
            )
            
        except Exception as e:
            logger.error(
                "candle_closed_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )

    async def handle_price_fluctuation(self, event: PriceFluctuationEvent):
        """Handle price fluctuation event and trigger ML pipeline.

        This triggers the same feature computation and prediction pipeline as candle close,
        but based on major price fluctuations instead of time-based intervals.

        Args:
            event: Price fluctuation event
        """
        try:
            payload = event.payload
            symbol = payload.get("symbol")
            change_pct = payload.get("change_pct")
            threshold_pct = payload.get("threshold_pct")

            # Update context with fluctuation data
            self.context_manager.update_context({
                "market_data": {
                    "symbol": symbol,
                    "price": payload.get("price"),
                    "previous_price": payload.get("previous_price"),
                    "change_pct": change_pct,
                    "volume": payload.get("volume"),
                    "timestamp": payload.get("timestamp"),
                    "fluctuation_triggered": True
                }
            })

            # Trigger feature computation - Request all 50 features required by ML models
            # This matches the FEATURE_LIST from training scripts and mcp_orchestrator
            feature_request = FeatureRequestEvent(
                source="market_data_handler",
                correlation_id=event.event_id,
                payload={
                    "symbol": symbol,
                    "feature_names": [
                        # Price-based (16 features)
                        'sma_10', 'sma_20', 'sma_50', 'sma_100', 'sma_200',
                        'ema_12', 'ema_26', 'ema_50',
                        'close_sma_20_ratio', 'close_sma_50_ratio', 'close_sma_200_ratio',
                        'high_low_spread', 'close_open_ratio', 'body_size', 'upper_shadow', 'lower_shadow',
                        # Momentum (10 features)
                        'rsi_14', 'rsi_7', 'stochastic_k_14', 'stochastic_d_14',
                        'williams_r_14', 'cci_20', 'roc_10', 'roc_20',
                        'momentum_10', 'momentum_20',
                        # Trend (8 features)
                        'macd', 'macd_signal', 'macd_histogram',
                        'adx_14', 'aroon_up', 'aroon_down', 'aroon_oscillator',
                        'trend_strength',
                        # Volatility (8 features)
                        'bb_upper', 'bb_lower', 'bb_width', 'bb_position',
                        'atr_14', 'atr_20',
                        'volatility_10', 'volatility_20',
                        # Volume (6 features)
                        'volume_sma_20', 'volume_ratio', 'obv',
                        'volume_price_trend', 'accumulation_distribution', 'chaikin_oscillator',
                        # Returns (2 features)
                        'returns_1h', 'returns_24h'
                    ],
                    "timestamp": payload.get("timestamp"),
                    "version": "latest"
                }
            )

            await event_bus.publish(feature_request)

            logger.info(
                "price_fluctuation_handled",
                symbol=symbol,
                change_pct=f"{change_pct:.2f}%",
                threshold_pct=f"{threshold_pct:.2f}%",
                price=payload.get("price"),
                message="Major price fluctuation detected - triggering ML pipeline (features -> models -> reasoning -> decision)",
                event_id=event.event_id,
                feature_request_id=feature_request.event_id
            )

        except Exception as e:
            logger.error(
                "price_fluctuation_handler_error",
                event_id=event.event_id,
                error=str(e),
                exc_info=True
            )

    async def register_handlers(self):
        """Register event handlers with event bus."""
        event_bus.subscribe(EventType.MARKET_TICK, self.handle_market_tick)
        event_bus.subscribe(EventType.PRICE_FLUCTUATION, self.handle_price_fluctuation)
        event_bus.subscribe(EventType.CANDLE_CLOSED, self.handle_candle_closed)

        logger.info("market_data_handlers_registered")


# Global handler instance
market_data_handler = MarketDataEventHandler()

