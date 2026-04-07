"""
Market data service.

Fetches and caches market data from Delta Exchange.
Supports event-driven streaming via event bus.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import asyncio
import time
import structlog

from agent.data.candle_store import CandleStore
from agent.data.delta_client import (
    DeltaExchangeClient,
    DeltaExchangeWebSocketClient,
    CircuitBreakerOpenError,
    DeltaExchangeError
)
from agent.core.redis_config import get_cache, set_cache
from agent.core.config import settings
from agent.events.event_bus import event_bus
from agent.events.schemas import MarketTickEvent, CandleClosedEvent, PriceFluctuationEvent, EventType

logger = structlog.get_logger()


class MarketDataService:
    """Market data service."""
    
    def __init__(self):
        """Initialize market data service."""
        self.delta_client = DeltaExchangeClient()
        self.websocket_client = DeltaExchangeWebSocketClient(
            api_key=settings.delta_exchange_api_key,
            api_secret=settings.delta_exchange_api_secret,
            base_url=settings.websocket_url,
            max_reconnect_attempts=settings.websocket_reconnect_attempts,
            reconnect_delay=settings.websocket_reconnect_delay,
            heartbeat_interval=settings.websocket_heartbeat_interval
        )
        self._websocket_enabled = settings.websocket_enabled
        self.cache_ttl = 60  # Cache for 60 seconds
        self.ticker_cache_ttl = 10  # Shorter cache for ticker
        self.streaming_symbols: List[str] = []
        self.streaming_running = False
        self._streaming_task: Optional[asyncio.Task] = None
        self._websocket_connected = False
        self._last_ticker_cache: Dict[str, Dict[str, Any]] = {}
        self._last_candle_cache: Dict[str, Dict[str, Any]] = {}
        self._tick_throttle_ms = 50  # Reduced throttling for real-time updates (20 per second max)
        self._last_tick_time: Dict[str, datetime] = {}
        self._tick_force_emit_interval = 2.0  # Force emit tick every 2 seconds for real-time display
        # New: Track last major price change for fluctuation threshold
        self._last_major_price: Dict[str, float] = {}
        self._price_fluctuation_threshold_pct = settings.price_fluctuation_threshold_pct
        # Cache for 24h stats fetched from REST API (fallback when WebSocket doesn't provide them)
        self._24h_stats_cache: Dict[str, Dict[str, Any]] = {}
        self._24h_stats_cache_ttl = 60  # Cache 24h stats for 60 seconds
        self._24h_stats_last_fetch: Dict[str, datetime] = {}
        self._24h_stats_fetch_task: Optional[asyncio.Task] = None
        self._last_sl_tp_check: Dict[str, float] = {}  # symbol -> time.time() for WebSocket SL/TP throttle
        self._candle_store = CandleStore()
        self._pipeline_direct_trigger: Optional[Any] = None
        self._ws_reconnect_backoff_seconds: float = 1.0

    def set_pipeline_direct_trigger(self, callback: Any) -> None:
        """Set callback for direct pipeline trigger when Redis is unavailable."""
        self._pipeline_direct_trigger = callback

    async def initialize(self):
        """Initialize market data service."""
        # Set up WebSocket message handler for ticker updates if WebSocket is enabled
        if self._websocket_enabled:
            self.websocket_client.add_message_handler("ticker", self._handle_websocket_ticker)
            self.websocket_client.add_message_handler("v2/ticker", self._handle_websocket_ticker)

            # Attempt to connect WebSocket
            try:
                await self._connect_websocket()
                logger.info("market_data_websocket_initialized", connected=self._websocket_connected)
            except Exception as e:
                logger.warning("websocket_initialization_failed", error=str(e))
                # Continue without WebSocket - will fall back to REST API
        else:
            logger.info("websocket_disabled", message="WebSocket streaming is disabled, using REST API polling only")
        
        # Start background task to periodically fetch 24h stats from REST API
        # This ensures we have 24h high/low even if WebSocket doesn't provide them
        if self._24h_stats_fetch_task is None or self._24h_stats_fetch_task.done():
            self._24h_stats_fetch_task = asyncio.create_task(self._periodic_24h_stats_fetch())

    async def _connect_websocket(self) -> None:
        """Connect to Delta Exchange WebSocket."""
        try:
            await self.websocket_client.connect()
            self._websocket_connected = True
            logger.info("market_data_websocket_connected")
        except Exception as e:
            logger.error("market_data_websocket_connection_failed", error=str(e))
            self._websocket_connected = False
            # Will fall back to REST API polling

    async def _handle_websocket_ticker(self, message: Dict[str, Any]) -> None:
        """Handle incoming WebSocket ticker message."""
        try:
            symbol = message.get("symbol")
            if not symbol:
                return

            # Convert WebSocket message to ticker format compatible with existing code
            ticker_data = {
                "symbol": symbol,
                "price": float(message.get("mark_price", 0)),
                "volume": float(message.get("volume", 0)),
                "timestamp": message.get("timestamp", 0),
                "bid": float(message.get("quotes", {}).get("best_bid", 0)),
                "ask": float(message.get("quotes", {}).get("best_ask", 0)),
                "mark_change_24h": message.get("mark_change_24h"),  # Price change percentage
                "open": float(message.get("open", 0)),
                "close": float(message.get("close", 0)),
                "high": float(message.get("high", 0)),
                "low": float(message.get("low", 0)),
                "oi": float(message.get("oi", 0)),  # Open interest
                "turnover_usd": float(message.get("turnover_usd", 0)),
                "spot_price": float(message.get("spot_price", 0))
            }

            # Process the ticker data (same logic as before)
            await self._process_ticker_update(symbol, ticker_data)

            # WebSocket-driven SL/TP: when enabled and position exists, trigger position check (throttled)
            if getattr(settings, "websocket_sl_tp_enabled", True):
                from agent.core.execution import execution_module
                pos = execution_module.position_manager.get_position(symbol)
                if pos and pos.get("status") == "open":
                    now = time.time()
                    if now - self._last_sl_tp_check.get(symbol, 0) >= 0.2:
                        self._last_sl_tp_check[symbol] = now
                        price = float(message.get("mark_price", 0) or message.get("close", 0))
                        if price > 0:
                            await execution_module.update_position_price_and_check(symbol, price)

        except Exception as e:
            logger.error(
                "websocket_ticker_handler_error",
                error=str(e),
                message=message,
                exc_info=True
            )

    async def _process_ticker_update(self, symbol: str, ticker_data: Dict[str, Any]) -> None:
        """Process ticker update from either WebSocket or REST API."""
        # Check for price fluctuations (same logic as before)
        await self._check_and_emit_ticker_with_fluctuation_from_data(symbol, ticker_data)

        # Update cache
        self._last_ticker_cache[symbol] = ticker_data
        self._last_tick_time[symbol] = datetime.now(timezone.utc)

    async def shutdown(self):
        """Shutdown market data service."""
        await self.stop_market_data_stream()
        # Disconnect WebSocket if enabled
        if self._websocket_enabled:
            await self.websocket_client.disconnect()
        # Cancel 24h stats fetch task
        if self._24h_stats_fetch_task and not self._24h_stats_fetch_task.done():
            self._24h_stats_fetch_task.cancel()
            try:
                await self._24h_stats_fetch_task
            except asyncio.CancelledError:
                pass
    
    async def start_market_data_stream(self, symbols: List[str], interval: str = "15m"):
        """Start streaming market data for symbols.

        Args:
            symbols: List of symbols to stream
            interval: Candle interval to monitor
        """
        if self.streaming_running:
            logger.warning("market_data_stream_already_running")
            return

        self.streaming_symbols = symbols
        self.streaming_running = True

        # Subscribe to WebSocket if enabled and connected
        if self._websocket_enabled and self._websocket_connected:
            try:
                await self.websocket_client.subscribe_ticker(symbols)
                logger.info("market_data_websocket_subscribed", symbols=symbols)
            except Exception as e:
                logger.warning("market_data_websocket_subscription_failed", error=str(e))
                # Fall back to REST API polling

        self._streaming_task = asyncio.create_task(self._stream_loop(interval))

        logger.info(
            "market_data_stream_started",
            symbols=symbols,
            interval=interval,
            websocket_enabled=self._websocket_connected
        )
    
    async def stop_market_data_stream(self):
        """Stop streaming market data."""
        self.streaming_running = False
        
        if self._streaming_task:
            self._streaming_task.cancel()
            try:
                await self._streaming_task
            except asyncio.CancelledError:
                pass
        
        logger.info("market_data_stream_stopped")
    
    async def _stream_loop(self, interval: str):
        """Main streaming loop - optimized for WebSocket or REST API fallback."""
        consecutive_errors = 0
        max_consecutive_errors = 10
        websocket_reconnect_attempts = 0
        max_websocket_reconnect_attempts = 5

        candle_poll_interval_seconds = getattr(settings, "candle_poll_interval_seconds", 30) or 30
        # Track when we last checked candles for each symbol.
        last_candle_check_time_by_symbol: Dict[str, float] = {}

        # Determine polling interval based on WebSocket availability
        # When WebSocket is connected, use fallback polling interval since we get real-time updates
        poll_interval = settings.fast_poll_interval if not (self._websocket_enabled and self._websocket_connected) else settings.websocket_fallback_poll_interval

        logger.info(
            "market_data_stream_mode",
            websocket_enabled=self._websocket_enabled,
            websocket_connected=self._websocket_connected,
            poll_interval=poll_interval,
            symbols=self.streaming_symbols
        )

        while self.streaming_running:
            try:
                # Check WebSocket connection health and reconnect if needed
                if self._websocket_enabled and not self._websocket_connected and websocket_reconnect_attempts < max_websocket_reconnect_attempts:
                    wait_s = min(self._ws_reconnect_backoff_seconds, 60.0)
                    if wait_s > 0:
                        logger.info(
                            "market_data_websocket_reconnect_backoff",
                            sleep_seconds=round(wait_s, 2),
                            attempt=websocket_reconnect_attempts + 1,
                        )
                        await asyncio.sleep(wait_s)
                    logger.info(
                        "market_data_attempting_websocket_reconnect",
                        attempt=websocket_reconnect_attempts + 1,
                        max_attempts=max_websocket_reconnect_attempts,
                        backoff_seconds=round(self._ws_reconnect_backoff_seconds, 2),
                    )
                    try:
                        await self._connect_websocket()
                        if self._websocket_connected:
                            # Re-subscribe to symbols
                            await self.websocket_client.subscribe_ticker(self.streaming_symbols)
                            logger.info("market_data_websocket_reconnected_and_subscribed", symbols=self.streaming_symbols)
                            websocket_reconnect_attempts = 0  # Reset on success
                            self._ws_reconnect_backoff_seconds = 1.0
                        else:
                            websocket_reconnect_attempts += 1
                            self._ws_reconnect_backoff_seconds = min(
                                self._ws_reconnect_backoff_seconds * 2.0, 60.0
                            )
                    except Exception as e:
                        logger.warning(
                            "market_data_websocket_reconnect_failed",
                            attempt=websocket_reconnect_attempts + 1,
                            error=str(e),
                            next_backoff_seconds=min(self._ws_reconnect_backoff_seconds * 2.0, 60.0),
                        )
                        websocket_reconnect_attempts += 1
                        self._ws_reconnect_backoff_seconds = min(
                            self._ws_reconnect_backoff_seconds * 2.0, 60.0
                        )

                for symbol in self.streaming_symbols:
                    # Only poll tickers via REST API if WebSocket is not available or enabled
                    if not (self._websocket_enabled and self._websocket_connected):
                        # Continuously monitor tickers for price fluctuations (REST fallback)
                        await self._check_and_emit_ticker_with_fluctuation(symbol)

                    # Keep candle monitoring via REST, but at a cadence independent from
                    # the ticker polling loop (especially important when WebSocket is connected).
                    now = time.time()
                    last_candle_check = last_candle_check_time_by_symbol.get(symbol, 0.0)
                    if now - last_candle_check >= candle_poll_interval_seconds:
                        await self._check_and_emit_candle(symbol, interval)
                        last_candle_check_time_by_symbol[symbol] = time.time()

                # Reset error count on successful iteration
                consecutive_errors = 0
                websocket_reconnect_attempts = 0

                # Use appropriate polling interval
                await asyncio.sleep(min(poll_interval, candle_poll_interval_seconds))

            except asyncio.CancelledError:
                break
            except CircuitBreakerOpenError as e:
                # Circuit breaker is OPEN - service unavailable
                # Don't increment consecutive_errors for circuit breaker - this is expected behavior
                # Log periodically to avoid spam
                if consecutive_errors == 0:  # Log first time
                    logger.warning(
                        "market_data_stream_circuit_breaker_open",
                        error=str(e),
                        message="Delta Exchange circuit breaker is OPEN - pausing stream. Will retry after timeout."
                    )
                # Sleep longer when circuit breaker is open to allow recovery
                # Circuit breaker will transition to HALF_OPEN after timeout
                await asyncio.sleep(30)  # Wait 30 seconds before retry
            except DeltaExchangeError as e:
                # Delta Exchange API error
                consecutive_errors += 1
                # Downgrade noisy transient Delta API failures to warnings and avoid
                # attaching full tracebacks (signal is in the circuit breaker + health score).
                logger.warning(
                    "market_data_stream_delta_exchange_error",
                    error=str(e),
                    consecutive_errors=consecutive_errors,
                )
                # Exponential backoff for API errors
                sleep_time = min(5 * (2 ** min(consecutive_errors, 4)), 60)
                await asyncio.sleep(sleep_time)
            except Exception as e:
                # Other unexpected errors
                consecutive_errors += 1
                logger.error(
                    "market_data_stream_loop_error",
                    error=str(e),
                    error_type=type(e).__name__,
                    consecutive_errors=consecutive_errors,
                    exc_info=True
                )
                # Stop streaming if too many consecutive errors
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(
                        "market_data_stream_stopped_too_many_errors",
                        consecutive_errors=consecutive_errors,
                        message="Stopping market data stream due to too many consecutive errors"
                    )
                    self.streaming_running = False
                    break
                await asyncio.sleep(5)
    
    async def _check_and_emit_ticker_with_fluctuation_from_data(self, symbol: str, ticker_data: Dict[str, Any]):
        """Process ticker data and emit both tick and fluctuation events as needed.

        Works with pre-fetched ticker data (from WebSocket or REST API).
        Emits MarketTickEvent for UI updates and PriceFluctuationEvent for ML pipeline triggers.

        Args:
            symbol: Trading symbol
            ticker_data: Ticker data dictionary
        """
        try:
            current_price = ticker_data["price"]

            # First, handle regular tick emission for UI updates
            await self._check_and_emit_ticker_from_data(symbol, ticker_data)

            # Now check for major price fluctuations that should trigger ML pipeline
            last_major_price = self._last_major_price.get(symbol)

            if last_major_price is not None:
                # Calculate percentage change from last major fluctuation
                price_change_pct = abs((current_price - last_major_price) / last_major_price) * 100

                # Check if change exceeds fluctuation threshold
                if price_change_pct >= self._price_fluctuation_threshold_pct:
                    # Emit fluctuation event for ML pipeline
                    await self._on_price_fluctuation(
                        symbol=symbol,
                        current_price=current_price,
                        previous_price=last_major_price,
                        change_pct=price_change_pct,
                        volume=ticker_data["volume"],
                        threshold_pct=self._price_fluctuation_threshold_pct
                    )

                    # Update last major price
                    self._last_major_price[symbol] = current_price
            else:
                # First price reading - set baseline
                self._last_major_price[symbol] = current_price

        except Exception as e:
            logger.error(
                "market_data_ticker_fluctuation_check_error",
                symbol=symbol,
                error=str(e),
                exc_info=True
            )

    async def _check_and_emit_ticker_from_data(self, symbol: str, ticker_data: Dict[str, Any]):
        """Check ticker data and emit tick event if changed (works with pre-fetched data).

        Emits tick if:
        1. Price changed by >0.001% (very sensitive for real-time updates)
        2. OR at least 2 seconds have passed since last tick (time-based fallback for realtime display)

        Args:
            symbol: Trading symbol
            ticker_data: Pre-fetched ticker data
        """
        try:
            # Throttle ticks (prevent too frequent updates)
            now = datetime.now(timezone.utc)
            last_tick_time = self._last_tick_time.get(symbol)
            if last_tick_time:
                elapsed_ms = (now - last_tick_time).total_seconds() * 1000
                if elapsed_ms < self._tick_throttle_ms:
                    return

            # Check if we should emit tick
            should_emit = False
            last_ticker = self._last_ticker_cache.get(symbol)

            if last_ticker:
                # Check if price changed significantly (>0.001% - very sensitive for real-time updates)
                price_change_pct = abs((ticker_data["price"] - last_ticker["price"]) / last_ticker["price"])
                if price_change_pct >= 0.00001:  # At least 0.001% change (very responsive)
                    should_emit = True
                else:
                    # Time-based fallback: emit tick at least every N seconds for real-time display
                    elapsed_seconds = (now - last_tick_time).total_seconds()
                    if elapsed_seconds >= self._tick_force_emit_interval:
                        should_emit = True
            else:
                # No previous ticker cached, always emit first tick
                should_emit = True

            if should_emit:
                # Emit tick event
                await self._on_tick(symbol, ticker_data)

                self._last_ticker_cache[symbol] = ticker_data
                self._last_tick_time[symbol] = now

        except Exception as e:
            logger.error(
                "market_data_ticker_check_error",
                symbol=symbol,
                error=str(e),
                exc_info=True
            )

    async def _check_and_emit_ticker_with_fluctuation(self, symbol: str):
        """Check ticker and emit both tick and fluctuation events as needed (REST API fallback).

        Emits MarketTickEvent for UI updates and PriceFluctuationEvent for ML pipeline triggers.
        """
        try:
            ticker = await self.get_ticker(symbol)
            if not ticker:
                return

            # Process using the unified method
            await self._process_ticker_update(symbol, ticker)

        except Exception as e:
            logger.error(
                "market_data_ticker_fluctuation_check_error",
                symbol=symbol,
                error=str(e),
                exc_info=True
            )

    async def _check_and_emit_candle(self, symbol: str, interval: str):
        """Check for new candle and emit candle closed event."""
        try:
            # Request more historical data to ensure we get completed candles
            market_data = await self.get_market_data(symbol, interval, limit=10)
            if not market_data or not market_data.get("candles"):
                return

            candles = market_data["candles"]
            if len(candles) < 1:
                return

            # Get the most recent completed candle
            # If we have multiple candles, use the second-to-last (completed)
            # If we only have one, it's the current forming candle - don't emit yet
            if len(candles) < 2:
                # Only one candle - it's still forming, don't emit
                return

            # Use the second-to-last candle as it's definitely completed
            completed_candle = candles[-2] if len(candles) >= 2 else candles[-1]
            last_candle_key = f"{symbol}:{interval}"
            last_candle = self._last_candle_cache.get(last_candle_key)

            # Check if this is a new completed candle
            if last_candle:
                if completed_candle.get("timestamp") == last_candle.get("timestamp"):
                    return  # Same candle already processed

            # Emit candle closed event for the completed candle
            await self._on_candle_close(symbol, interval, completed_candle)

            self._last_candle_cache[last_candle_key] = completed_candle

        except Exception as e:
            logger.error(
                "market_data_candle_check_error",
                symbol=symbol,
                interval=interval,
                error=str(e),
                exc_info=True
            )
    
    async def _on_tick(self, symbol: str, ticker_data: Dict[str, Any]):
        """Handle tick event and emit to event bus.
        
        Args:
            symbol: Trading symbol
            ticker_data: Ticker data dictionary
        """
        try:
            # Extract timestamp
            timestamp_raw = ticker_data.get("timestamp")
            if isinstance(timestamp_raw, str):
                timestamp = datetime.fromisoformat(timestamp_raw)
            elif isinstance(timestamp_raw, (int, float)):
                # Handle Unix timestamp - Delta Exchange sends microseconds (13 digits)
                # or milliseconds (10 digits), or seconds (10 digits before decimal)
                if timestamp_raw > 1e12:  # Microseconds (13+ digits)
                    timestamp = datetime.fromtimestamp(timestamp_raw / 1_000_000, tz=timezone.utc)
                elif timestamp_raw > 1e10:  # Milliseconds (10-12 digits)
                    timestamp = datetime.fromtimestamp(timestamp_raw / 1_000, tz=timezone.utc)
                else:  # Seconds (10 or fewer digits)
                    timestamp = datetime.fromtimestamp(timestamp_raw, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            # Create payload with all available market data
            payload = {
                "symbol": symbol,
                "price": float(ticker_data.get("price", 0.0)),
                "volume": float(ticker_data.get("volume", 0.0)),
                "timestamp": timestamp,
            }

            # Add 24h statistics if available (from Delta Exchange WebSocket)
            if "mark_change_24h" in ticker_data:
                payload["change_24h_pct"] = float(ticker_data["mark_change_24h"])
            if "open" in ticker_data:
                payload["open_24h"] = float(ticker_data["open"])
            if "high" in ticker_data:
                payload["high_24h"] = float(ticker_data["high"])
            if "low" in ticker_data:
                payload["low_24h"] = float(ticker_data["low"])
            if "close" in ticker_data:
                payload["close_24h"] = float(ticker_data["close"])
            
            # Fallback: If WebSocket didn't provide 24h high/low, use cached REST API data
            if "high_24h" not in payload or "low_24h" not in payload:
                cached_stats = self._24h_stats_cache.get(symbol)
                if cached_stats:
                    if "high_24h" not in payload and "high_24h" in cached_stats:
                        payload["high_24h"] = cached_stats["high_24h"]
                    if "low_24h" not in payload and "low_24h" in cached_stats:
                        payload["low_24h"] = cached_stats["low_24h"]
                    if "open_24h" not in payload and "open_24h" in cached_stats:
                        payload["open_24h"] = cached_stats["open_24h"]
                    if "change_24h_pct" not in payload and "change_24h_pct" in cached_stats:
                        payload["change_24h_pct"] = cached_stats["change_24h_pct"]
            if "turnover_usd" in ticker_data:
                payload["turnover_usd"] = float(ticker_data["turnover_usd"])
            if "oi" in ticker_data:
                payload["oi"] = float(ticker_data["oi"])
            if "spot_price" in ticker_data:
                payload["spot_price"] = float(ticker_data["spot_price"])
            if "mark_price" in ticker_data:
                payload["mark_price"] = float(ticker_data["mark_price"])

            # Add order book data if available
            if "quotes" in ticker_data:
                quotes = ticker_data["quotes"]
                if "best_bid" in quotes:
                    payload["bid_price"] = float(quotes["best_bid"])
                if "best_ask" in quotes:
                    payload["ask_price"] = float(quotes["best_ask"])
                if "bid_size" in quotes:
                    payload["bid_size"] = float(quotes["bid_size"])
                if "ask_size" in quotes:
                    payload["ask_size"] = float(quotes["ask_size"])

            # Calculate absolute change if percentage is available
            if payload.get("change_24h_pct") is not None and payload.get("open_24h") is not None:
                change_pct = payload["change_24h_pct"]
                open_price = payload["open_24h"]
                payload["change_24h"] = open_price * (change_pct / 100)

            event = MarketTickEvent(
                source="market_data_service",
                payload=payload
            )
            
            await event_bus.publish(event)
            
            logger.debug(
                "market_tick_event_emitted",
                symbol=symbol,
                price=ticker_data.get("price"),
                event_id=event.event_id
            )
            
        except Exception as e:
            logger.error(
                "market_tick_event_emit_failed",
                symbol=symbol,
                error=str(e),
                exc_info=True
            )
    
    async def _on_candle_close(self, symbol: str, interval: str, candle_data: Dict[str, Any]):
        """Handle candle close event and emit to event bus.
        
        Args:
            symbol: Trading symbol
            interval: Candle interval
            candle_data: Candle data dictionary
        """
        try:
            # Parse timestamp - ensure UTC timezone
            timestamp = candle_data.get("timestamp")
            if isinstance(timestamp, str):
                # Parse ISO format string
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                # Ensure UTC timezone
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                else:
                    timestamp = timestamp.astimezone(timezone.utc)
            elif isinstance(timestamp, (int, float)):
                # Parse Unix timestamp - fromtimestamp uses local timezone, so convert to UTC
                timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            else:
                # Use current UTC time
                timestamp = datetime.now(timezone.utc)
            
            # Persist candle for reproducible training and backtesting
            try:
                candle_for_store = {
                    "open": float(candle_data.get("open", 0)),
                    "high": float(candle_data.get("high", 0)),
                    "low": float(candle_data.get("low", 0)),
                    "close": float(candle_data.get("close", 0)),
                    "volume": float(candle_data.get("volume", 0)),
                    "timestamp": timestamp.timestamp() if hasattr(timestamp, "timestamp") else timestamp,
                }
                self._candle_store.append(symbol, interval, [candle_for_store])
            except Exception as store_err:
                logger.warning(
                    "candle_store_persist_failed",
                    symbol=symbol,
                    interval=interval,
                    error=str(store_err),
                )

            event = CandleClosedEvent(
                source="market_data_service",
                payload={
                    "symbol": symbol,
                    "interval": interval,
                    "open": float(candle_data.get("open", 0)),
                    "high": float(candle_data.get("high", 0)),
                    "low": float(candle_data.get("low", 0)),
                    "close": float(candle_data.get("close", 0)),
                    "volume": float(candle_data.get("volume", 0)),
                    "timestamp": timestamp
                }
            )

            published = await event_bus.publish(event)
            if not published and self._pipeline_direct_trigger:
                # Redis unavailable: trigger pipeline directly (polling fallback)
                try:
                    await self._pipeline_direct_trigger(symbol, {"interval": interval})
                    logger.info(
                        "candle_closed_pipeline_direct_trigger",
                        symbol=symbol,
                        interval=interval,
                        message="Redis unavailable - triggered pipeline directly",
                    )
                except Exception as trigger_err:
                    logger.error(
                        "candle_closed_direct_trigger_failed",
                        symbol=symbol,
                        interval=interval,
                        error=str(trigger_err),
                        exc_info=True,
                    )
            elif published:
                logger.info(
                    "candle_closed_event_emitted",
                    symbol=symbol,
                    interval=interval,
                    close=candle_data.get("close"),
                    event_id=event.event_id
                )
            
        except Exception as e:
            logger.error(
                "candle_closed_event_emit_failed",
                symbol=symbol,
                interval=interval,
                error=str(e),
                exc_info=True
            )

    async def _on_price_fluctuation(self, symbol: str, current_price: float, previous_price: float,
                                   change_pct: float, volume: float, threshold_pct: float):
        """Handle price fluctuation event and emit to event bus.

        Args:
            symbol: Trading symbol
            current_price: Current price
            previous_price: Previous major price level
            change_pct: Percentage change from previous major price
            volume: Trading volume
            threshold_pct: Threshold percentage that triggered this event
        """
        try:
            event = PriceFluctuationEvent(
                source="market_data_service",
                payload={
                    "symbol": symbol,
                    "price": current_price,
                    "previous_price": previous_price,
                    "change_pct": change_pct,
                    "volume": volume,
                    "timestamp": datetime.now(timezone.utc),
                    "threshold_pct": threshold_pct
                }
            )

            await event_bus.publish(event)

            logger.info(
                "price_fluctuation_event_emitted",
                symbol=symbol,
                current_price=current_price,
                previous_price=previous_price,
                change_pct=f"{change_pct:.2f}%",
                threshold_pct=f"{threshold_pct:.2f}%",
                event_id=event.event_id,
                message="Major price fluctuation detected - triggering ML pipeline"
            )

        except Exception as e:
            logger.error(
                "price_fluctuation_event_emit_failed",
                symbol=symbol,
                current_price=current_price,
                previous_price=previous_price,
                change_pct=change_pct,
                error=str(e),
                exc_info=True
            )

    async def get_market_data(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100
    ) -> Optional[Dict[str, Any]]:
        """Get market data (OHLCV candles)."""
        
        # Check cache first
        cache_key = f"market_data:{symbol}:{interval}:{limit}"
        cached = await get_cache(cache_key)
        if cached:
            return cached
        
        try:
            # Map interval to Delta Exchange resolution (must be lowercase)
            resolution_map = {
                "1m": "1m",
                "3m": "3m",
                "5m": "5m",
                "15m": "15m",
                "30m": "30m",
                "1h": "1h",
                "2h": "2h",
                "4h": "4h",
                "1d": "1d",
            }
            resolution = resolution_map.get(interval, "1h")
            
            # Calculate start and end timestamps from limit and interval.
            start_time, end_time = self.delta_client._calculate_candle_time_range(
                resolution, limit
            )
            
            # Fetch from Delta Exchange
            response = await self.delta_client.get_candles(
                symbol=symbol,
                resolution=resolution,
                start=start_time,
                end=end_time
            )
            
            # Parse response - handle different response structures
            # API might return {"result": {"candles": [...]}} or {"result": [...]} or just [...]
            candles = []
            if isinstance(response, dict):
                result = response.get("result")
                if isinstance(result, dict):
                    candles = result.get("candles", [])
                elif isinstance(result, list):
                    candles = result
            elif isinstance(response, list):
                candles = response
            
            # Convert to standard format
            formatted_candles = []
            for candle in candles:
                formatted_candles.append({
                    "timestamp": candle.get("time"),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "close": float(candle.get("close", 0)),
                    "volume": float(candle.get("volume", 0))
                })
            
            # Get latest ticker for current price
            ticker = await self.get_ticker(symbol)
            current_price = ticker.get("close") if ticker else None
            
            market_data = {
                "symbol": symbol,
                "interval": interval,
                "candles": formatted_candles,
                "current_price": current_price,
                "data_age_seconds": 0,  # Fresh data
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Cache result
            await set_cache(cache_key, market_data, ttl=self.cache_ttl)
            
            return market_data
            
        except CircuitBreakerOpenError as e:
            # Circuit breaker is OPEN - service unavailable, return None gracefully
            logger.warning(
                "market_data_service_circuit_breaker_open",
                symbol=symbol,
                interval=interval,
                limit=limit,
                message="Delta Exchange circuit breaker is OPEN - service unavailable"
            )
            return None
        except DeltaExchangeError as e:
            # Delta Exchange API error - log and return None
            logger.warning(
                "market_data_service_delta_exchange_error",
                symbol=symbol,
                interval=interval,
                limit=limit,
                error=str(e),
            )
            return None
        except Exception as e:
            # Other unexpected errors
            logger.error(
                "market_data_service_fetch_failed",
                symbol=symbol,
                interval=interval,
                limit=limit,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return None
    
    async def get_ticker(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current ticker information."""
        
        # Check cache first
        cache_key = f"ticker:{symbol}"
        cached = await get_cache(cache_key)
        if cached:
            return cached
        
        try:
            # Fetch from Delta Exchange
            response = await self.delta_client.get_ticker(symbol)
            
            # Parse response
            ticker_data = response.get("result", {})
            
            ticker = {
                "symbol": symbol,
                "price": float(ticker_data.get("close", 0)),
                "open": float(ticker_data.get("open", 0)),
                "high": float(ticker_data.get("high", 0)),
                "low": float(ticker_data.get("low", 0)),
                "volume": float(ticker_data.get("volume", 0)),
                "change_24h": float(ticker_data.get("change_24h", 0)),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Cache result
            await set_cache(cache_key, ticker, ttl=self.ticker_cache_ttl)
            
            return ticker
            
        except CircuitBreakerOpenError as e:
            # Circuit breaker is OPEN - service unavailable, return None gracefully
            logger.warning(
                "market_data_service_ticker_circuit_breaker_open",
                symbol=symbol,
                message="Delta Exchange circuit breaker is OPEN - service unavailable"
            )
            return None
        except DeltaExchangeError as e:
            # Delta Exchange API error - log and return None
            logger.warning(
                "market_data_service_ticker_delta_exchange_error",
                symbol=symbol,
                error=str(e),
            )
            return None
        except Exception as e:
            # Other unexpected errors
            logger.error(
                "market_data_service_ticker_failed",
                symbol=symbol,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            return None
    
    async def get_orderbook(self, symbol: str, depth: int = 20) -> Optional[Dict[str, Any]]:
        """Get order book."""
        
        try:
            # Fetch from Delta Exchange
            response = await self.delta_client.get_orderbook(symbol, depth=depth)
            
            # Parse response
            orderbook_data = response.get("result", {})
            
            return {
                "symbol": symbol,
                "bids": orderbook_data.get("buy", []),
                "asks": orderbook_data.get("sell", []),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(
                "market_data_service_orderbook_failed",
                symbol=symbol,
                depth=depth,
                error=str(e),
                exc_info=True
            )
            return None
    
    async def _periodic_24h_stats_fetch(self):
        """Periodically fetch 24h stats from REST API for active symbols.
        
        This ensures we have 24h high/low even if WebSocket doesn't provide them.
        Runs every 60 seconds.
        """
        while True:
            try:
                await asyncio.sleep(60)  # Wait 60 seconds between fetches
                
                # Fetch stats for all active streaming symbols
                symbols_to_fetch = list(set(self.streaming_symbols))
                if not symbols_to_fetch:
                    # If no streaming symbols, fetch for default symbol
                    symbols_to_fetch = ["BTCUSD"]
                
                for symbol in symbols_to_fetch:
                    try:
                        # Check if cache is still valid
                        last_fetch = self._24h_stats_last_fetch.get(symbol)
                        if last_fetch:
                            time_since_fetch = (datetime.now(timezone.utc) - last_fetch).total_seconds()
                            if time_since_fetch < self._24h_stats_cache_ttl:
                                continue  # Cache still valid, skip
                        
                        # Fetch ticker data from REST API
                        ticker = await self.get_ticker(symbol)
                        if ticker:
                            # Extract 24h stats
                            stats = {
                                "high_24h": ticker.get("high", 0),
                                "low_24h": ticker.get("low", 0),
                                "open_24h": ticker.get("open", 0),
                                "change_24h_pct": ticker.get("change_24h", 0),
                            }
                            
                            # Update cache
                            self._24h_stats_cache[symbol] = stats
                            self._24h_stats_last_fetch[symbol] = datetime.now(timezone.utc)
                            
                            logger.debug(
                                "market_data_24h_stats_fetched",
                                symbol=symbol,
                                high_24h=stats.get("high_24h"),
                                low_24h=stats.get("low_24h")
                            )
                    except Exception as e:
                        logger.warning(
                            "market_data_24h_stats_fetch_error",
                            symbol=symbol,
                            error=str(e)
                        )
                        # Continue with other symbols
                        continue
                        
            except asyncio.CancelledError:
                logger.info("market_data_24h_stats_fetch_cancelled")
                break
            except Exception as e:
                logger.error(
                    "market_data_24h_stats_fetch_loop_error",
                    error=str(e),
                    exc_info=True
                )
                # Continue loop even on error
                await asyncio.sleep(60)
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        
        circuit_breaker_state = self.delta_client.get_circuit_breaker_state()
        
        return {
            "status": "up" if circuit_breaker_state["state"] != "OPEN" else "down",
            "circuit_breaker": circuit_breaker_state
        }

