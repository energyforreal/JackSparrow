"""
Market data service.

Fetches and caches market data from Delta Exchange.
Supports event-driven streaming via event bus.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta, timezone
import asyncio
import structlog

from agent.data.delta_client import DeltaExchangeClient, CircuitBreakerOpenError, DeltaExchangeError
from agent.core.redis import get_cache, set_cache
from agent.core.config import settings
from agent.events.event_bus import event_bus
from agent.events.schemas import MarketTickEvent, CandleClosedEvent, PriceFluctuationEvent, EventType

logger = structlog.get_logger()


class MarketDataService:
    """Market data service."""
    
    def __init__(self):
        """Initialize market data service."""
        self.delta_client = DeltaExchangeClient()
        self.cache_ttl = 60  # Cache for 60 seconds
        self.ticker_cache_ttl = 10  # Shorter cache for ticker
        self.streaming_symbols: List[str] = []
        self.streaming_running = False
        self._streaming_task: Optional[asyncio.Task] = None
        self._last_ticker_cache: Dict[str, Dict[str, Any]] = {}
        self._last_candle_cache: Dict[str, Dict[str, Any]] = {}
        self._tick_throttle_ms = 100  # Throttle ticks to max 10 per second per symbol
        self._last_tick_time: Dict[str, datetime] = {}
        self._tick_force_emit_interval = 5.0  # Force emit tick every 5 seconds even if price hasn't changed much
        # New: Track last major price change for fluctuation threshold
        self._last_major_price: Dict[str, float] = {}
        self._price_fluctuation_threshold_pct = settings.price_fluctuation_threshold_pct
    
    async def initialize(self):
        """Initialize market data service."""
        pass
    
    async def shutdown(self):
        """Shutdown market data service."""
        await self.stop_market_data_stream()
    
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
        self._streaming_task = asyncio.create_task(self._stream_loop(interval))
        
        logger.info(
            "market_data_stream_started",
            symbols=symbols,
            interval=interval
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
        """Main streaming loop - now continuously monitors price fluctuations."""
        consecutive_errors = 0
        max_consecutive_errors = 10

        while self.streaming_running:
            try:
                for symbol in self.streaming_symbols:
                    # Continuously monitor tickers for price fluctuations
                    await self._check_and_emit_ticker_with_fluctuation(symbol)
                    # Keep candle monitoring for longer-term analysis (less frequent)
                    await self._check_and_emit_candle(symbol, interval)

                # Reset error count on successful iteration
                consecutive_errors = 0

                # Use fast polling interval for continuous price monitoring
                # This controls how often we check for price updates
                await asyncio.sleep(settings.fast_poll_interval)

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
                logger.error(
                    "market_data_stream_delta_exchange_error",
                    error=str(e),
                    consecutive_errors=consecutive_errors,
                    exc_info=True
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
    
    def _get_interval_seconds(self, interval: str) -> int:
        """Get sleep seconds for interval."""
        interval_map = {
            "15m": 15,
            "1h": 60,
            "4h": 240,
            "1d": 86400
        }
        return interval_map.get(interval, 60)
    
    @staticmethod
    def _calculate_candle_time_range(resolution: str, candle_count: int) -> tuple[int, int]:
        """Calculate start and end timestamps for candle request.
        
        Args:
            resolution: Candle resolution (e.g., "15m", "1h", "4h", "1d")
            candle_count: Number of candles to retrieve
            
        Returns:
            Tuple of (start_timestamp, end_timestamp) in Unix seconds
        """
        import time
        
        # Map resolution to seconds per candle
        resolution_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900,
            "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
            "6h": 21600, "1d": 86400, "1w": 604800
        }
        
        seconds_per_candle = resolution_seconds.get(resolution.lower(), 3600)
        total_seconds = candle_count * seconds_per_candle
        
        end_time = int(time.time())
        start_time = end_time - total_seconds
        
        return start_time, end_time
    
    async def _check_and_emit_ticker(self, symbol: str):
        """Check ticker and emit tick event if changed.
        
        Emits tick if:
        1. Price changed by >0.01% (reduced from 0.1% for more frequent updates)
        2. OR at least 5 seconds have passed since last tick (time-based fallback for realtime display)
        """
        try:
            ticker = await self.get_ticker(symbol)
            if not ticker:
                return
            
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
                # Check if price changed significantly (>0.01% - reduced threshold for more frequent updates)
                price_change_pct = abs((ticker["price"] - last_ticker["price"]) / last_ticker["price"])
                if price_change_pct >= 0.0001:  # At least 0.01% change
                    should_emit = True
                else:
                    # Time-based fallback: emit tick at least every N seconds even if price hasn't changed much
                    elapsed_seconds = (now - last_tick_time).total_seconds()
                    if elapsed_seconds >= self._tick_force_emit_interval:
                        should_emit = True
            else:
                # No previous ticker cached, always emit first tick
                should_emit = True
            
            if should_emit:
                # Emit tick event
                await self._on_tick(symbol, ticker)
                
                self._last_ticker_cache[symbol] = ticker
                self._last_tick_time[symbol] = now
            
        except Exception as e:
            logger.error(
                "market_data_ticker_check_error",
                symbol=symbol,
                error=str(e),
                exc_info=True
            )

    async def _check_and_emit_ticker_with_fluctuation(self, symbol: str):
        """Check ticker and emit both tick and fluctuation events as needed.

        Emits MarketTickEvent for UI updates and PriceFluctuationEvent for ML pipeline triggers.
        """
        try:
            ticker = await self.get_ticker(symbol)
            if not ticker:
                return

            current_price = ticker["price"]

            # First, handle regular tick emission for UI updates
            await self._check_and_emit_ticker(symbol)

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
                        volume=ticker["volume"],
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

    async def _check_and_emit_candle(self, symbol: str, interval: str):
        """Check for new candle and emit candle closed event."""
        try:
            market_data = await self.get_market_data(symbol, interval, limit=2)
            if not market_data or not market_data.get("candles"):
                return
            
            candles = market_data["candles"]
            if len(candles) < 2:
                return
            
            latest_candle = candles[-1]
            last_candle_key = f"{symbol}:{interval}"
            last_candle = self._last_candle_cache.get(last_candle_key)
            
            # Check if this is a new candle
            if last_candle:
                if latest_candle.get("timestamp") == last_candle.get("timestamp"):
                    return  # Same candle, not closed yet
            
            # Emit candle closed event
            await self._on_candle_close(symbol, interval, latest_candle)
            
            self._last_candle_cache[last_candle_key] = latest_candle
            
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
            event = MarketTickEvent(
                source="market_data_service",
                payload={
                    "symbol": symbol,
                    "price": ticker_data.get("price", 0.0),
                    "volume": ticker_data.get("volume", 0.0),
                    "timestamp": datetime.fromisoformat(ticker_data.get("timestamp", datetime.now(timezone.utc).isoformat()))
                    if isinstance(ticker_data.get("timestamp"), str)
                    else ticker_data.get("timestamp", datetime.now(timezone.utc))
                }
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
            
            await event_bus.publish(event)
            
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
                "15m": "15m",
                "1h": "1h",
                "4h": "4h",
                "1d": "1d"
            }
            resolution = resolution_map.get(interval, "1h")
            
            # Calculate start and end timestamps from limit and interval
            start_time, end_time = self._calculate_candle_time_range(resolution, limit)
            
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
            logger.error(
                "market_data_service_delta_exchange_error",
                symbol=symbol,
                interval=interval,
                limit=limit,
                error=str(e),
                exc_info=True
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
            logger.error(
                "market_data_service_ticker_delta_exchange_error",
                symbol=symbol,
                error=str(e),
                exc_info=True
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
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status."""
        
        circuit_breaker_state = self.delta_client.get_circuit_breaker_state()
        
        return {
            "status": "up" if circuit_breaker_state["state"] != "OPEN" else "down",
            "circuit_breaker": circuit_breaker_state
        }

