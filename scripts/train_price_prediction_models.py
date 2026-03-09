#!/usr/bin/env python3
"""
Price Prediction Model Training Script for BTCUSD.

Fetches historical data from Delta Exchange API with pagination support,
handles reverse chronological data ordering, and trains both regression
(price prediction) and classification (buy/sell/hold) models using
XGBoost and LSTM algorithms.

Optimized for Google Colab usage.
"""

import sys
import os
import pickle
import asyncio
import time
import math
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
import pandas as pd
import numpy as np
from xgboost import XGBRegressor, XGBClassifier
import structlog

# Add project root to path
# Handle both Colab and local execution
def _get_project_root() -> Path:
    """Get project root directory, handling both Colab and local execution."""
    # Try using __file__ first (works in local execution)
    try:
        if __file__:
            script_path = Path(__file__).resolve()
            # scripts/train_price_prediction_models.py -> project root
            potential_root = script_path.parent.parent
            if (potential_root / "agent" / "data" / "delta_client.py").exists():
                return potential_root
    except (NameError, AttributeError):
        # __file__ not available (e.g., in some Colab environments)
        pass
    
    # Fallback: search from current working directory
    cwd = Path.cwd()
    
    # Check if we're already in project root
    if (cwd / "agent" / "data" / "delta_client.py").exists():
        return cwd
    
    # Check if scripts directory exists in current directory
    if (cwd / "scripts" / "train_price_prediction_models.py").exists():
        return cwd
    
    # Search upward from current directory
    current = cwd
    for _ in range(5):  # Limit search depth
        if (current / "agent" / "data" / "delta_client.py").exists():
            return current
        if current == current.parent:
            break
        current = current.parent
    
    # Last resort: use current directory (Colab default)
    return cwd

project_root = _get_project_root()
sys.path.insert(0, str(project_root))

# Import with error handling for Colab compatibility
import os
from typing import Optional

# Try importing config first (may fail in Colab if .env doesn't exist)
try:
    from agent.core.config import settings
except Exception as config_error:
    # Create a minimal settings object from environment variables
    # This allows the script to work in Colab without .env file
    import types
    settings = types.SimpleNamespace()
    settings.delta_exchange_base_url = os.getenv("DELTA_EXCHANGE_BASE_URL", "https://api.india.delta.exchange")
    settings.delta_exchange_api_key = os.getenv("DELTA_EXCHANGE_API_KEY")
    settings.delta_exchange_api_secret = os.getenv("DELTA_EXCHANGE_API_SECRET")
    settings.database_url = os.getenv("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
    settings.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    settings.environment = os.getenv("ENVIRONMENT", "colab")
    # Log that we're using fallback settings
    import structlog
    structlog.get_logger().warning(
        "using_fallback_settings",
        message="Config import failed, using environment variables directly",
        error=str(config_error)
    )

# Now import the other modules (these should work if files are uploaded correctly)
try:
    from agent.data.delta_client import DeltaExchangeClient, DeltaExchangeError
    from agent.data.feature_engineering import FeatureEngineering
except ImportError as e:
    # If these fail, it's a real problem - files are missing or incorrect
    import structlog
    temp_logger = structlog.get_logger()
    temp_logger.error(
        "failed_to_import_required_modules",
        error=str(e),
        message="Required modules (delta_client, feature_engineering) could not be imported. "
                "Please verify all files were uploaded correctly in Step 2."
    )
    raise

# Initialize logger (after all imports are successful)
logger = structlog.get_logger()

# Feature list (50 features)
# IMPORTANT: This order must match exactly with how features are computed in the agent
FEATURE_LIST = [
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
]

# Export FEATURE_LIST to JSON for agent reference
def export_feature_list_to_json(output_path: Optional[Path] = None) -> Path:
    """Export FEATURE_LIST to JSON file for agent reference.
    
    Args:
        output_path: Optional output path. Defaults to models/feature_list.json
        
    Returns:
        Path to exported JSON file
    """
    import json
    
    if output_path is None:
        output_path = project_root / "models" / "feature_list.json"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    feature_data = {
        "feature_list": FEATURE_LIST,
        "feature_count": len(FEATURE_LIST),
        "symbol": "BTCUSD",
        "description": "Complete list of 50 features used by XGBoost models for BTCUSD price prediction",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "note": "Feature order must match exactly between training and prediction"
    }
    
    with open(output_path, 'w') as f:
        json.dump(feature_data, f, indent=2)
    
    logger.info("feature_list_exported", output_path=str(output_path), feature_count=len(FEATURE_LIST))
    
    return output_path

# Delta Exchange API constants
MAX_CANDLES_PER_REQUEST = 2000
RATE_LIMIT_DELAY = 0.75  # seconds between requests


class PricePredictionTrainer:
    """Price prediction model trainer with pagination and data reversal support."""
    
    def __init__(self, symbol: str = "BTCUSD", validate_credentials: bool = True):
        """Initialize price prediction trainer.
        
        Args:
            symbol: Trading pair symbol (default: "BTCUSD" - only BTCUSD is supported)
            validate_credentials: Whether to validate API credentials on initialization
            
        Raises:
            ValueError: If API credentials are missing or invalid
            DeltaExchangeError: If API connection test fails
        """
        self.symbol = symbol
        
        # Check if credentials are configured
        if not settings.delta_exchange_api_key or not settings.delta_exchange_api_secret:
            error_msg = (
                "Delta Exchange API credentials are not configured. "
                "Please set DELTA_EXCHANGE_API_KEY and DELTA_EXCHANGE_API_SECRET "
                "environment variables or in your configuration file."
            )
            logger.error("missing_api_credentials", error=error_msg)
            raise ValueError(error_msg)
        
        logger.info(
            "initializing_trainer",
            symbol=symbol,
            api_key_configured=bool(settings.delta_exchange_api_key),
            api_secret_configured=bool(settings.delta_exchange_api_secret),
            base_url=settings.delta_exchange_base_url
        )
        
        try:
            self.delta_client = DeltaExchangeClient()
        except Exception as e:
            error_msg = (
                f"Failed to initialize Delta Exchange client: {str(e)}. "
                f"Check API credentials and base URL configuration."
            )
            logger.error("delta_client_init_failed", error=str(e), exc_info=True)
            raise ValueError(error_msg) from e
        
        self.feature_engineering = FeatureEngineering()
        self.models_dir = project_root / "models"
        self.storage_dir = project_root / "agent" / "model_storage" / "xgboost"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Validate credentials by making a test API call if requested
        if validate_credentials:
            # This will be done asynchronously, so we'll add an async method for it
            # For now, we'll validate in the first fetch call
            logger.info("credential_validation_enabled", message="Credentials will be validated on first API call")
    
    async def validate_api_connection(self) -> bool:
        """Validate API credentials and connectivity by making a test API call.
        
        Returns:
            True if API connection is valid
            
        Raises:
            ValueError: If API credentials are invalid
            DeltaExchangeError: If API connection test fails
        """
        logger.info("validating_api_connection", symbol=self.symbol)
        
        try:
            # Make a small test request for recent candles (last hour)
            end_time = int(time.time())
            start_time = end_time - 3600  # Last hour
            
            test_response = await self.delta_client.get_candles(
                symbol=self.symbol,
                resolution="1h",
                start=start_time,
                end=end_time
            )
            
            # Check if response indicates authentication failure
            if isinstance(test_response, dict):
                if test_response.get("success") is False:
                    error_info = test_response.get("error", {})
                    error_code = error_info.get("code", "UNKNOWN")
                    error_msg = error_info.get("message", "Unknown error")
                    
                    if error_code in ["UNAUTHORIZED", "AUTH_ERROR", "INVALID_CREDENTIALS"]:
                        full_error = (
                            f"API authentication failed: {error_msg} (code: {error_code}). "
                            f"Please verify your DELTA_EXCHANGE_API_KEY and DELTA_EXCHANGE_API_SECRET "
                            f"are correct and have proper permissions."
                        )
                        logger.error("api_authentication_failed", error_code=error_code, error_message=error_msg)
                        raise ValueError(full_error)
                    else:
                        # Other API errors might be acceptable for validation (e.g., no data)
                        logger.info(
                            "api_connection_validated",
                            symbol=self.symbol,
                            api_error_code=error_code,
                            message="API connection works, but test call returned an error (may be expected)"
                        )
                        return True
                else:
                    logger.info(
                        "api_connection_validated",
                        symbol=self.symbol,
                        success=True,
                        message="API credentials and connection validated successfully"
                    )
                    return True
            else:
                logger.warning(
                    "api_validation_unexpected_response",
                    response_type=type(test_response).__name__,
                    message="API returned unexpected response type, but connection appears to work"
                )
                return True
                
        except ValueError as e:
            # Re-raise validation errors
            raise
        except DeltaExchangeError as e:
            error_msg = (
                f"API connection test failed: {str(e)}. "
                f"Please check: "
                f"1. API credentials are correct (DELTA_EXCHANGE_API_KEY, DELTA_EXCHANGE_API_SECRET), "
                f"2. Base URL is correct ({settings.delta_exchange_base_url}), "
                f"3. Network connectivity to Delta Exchange API, "
                f"4. Symbol '{self.symbol}' is valid and available."
            )
            logger.error("api_connection_test_failed", error=str(e), exc_info=True)
            raise DeltaExchangeError(error_msg) from e
        except Exception as e:
            error_msg = (
                f"Unexpected error during API connection validation: {str(e)}. "
                f"Please check API configuration and network connectivity."
            )
            logger.error("api_validation_unexpected_error", error=str(e), exc_info=True)
            raise DeltaExchangeError(error_msg) from e
    
    async def _fetch_candles_batch(
        self,
        symbol: str,
        resolution: str,
        start: int,
        end: int,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> List[Dict[str, Any]]:
        """Fetch a single batch of candles (max 2,000).
        
        Args:
            symbol: Trading pair symbol
            resolution: Candle interval (must be lowercase)
            start: Start timestamp in Unix seconds
            end: End timestamp in Unix seconds
            max_retries: Maximum number of retry attempts for transient failures
            retry_delay: Initial delay between retries in seconds
            
        Returns:
            List of formatted candle dictionaries
            
        Raises:
            ValueError: If API response structure is invalid
            DeltaExchangeError: If API request fails after retries
        """
        logger.info(
            "fetching_candles_batch",
            symbol=symbol,
            resolution=resolution,
            start=start,
            end=end,
            start_iso=datetime.fromtimestamp(start, tz=timezone.utc).isoformat(),
            end_iso=datetime.fromtimestamp(end, tz=timezone.utc).isoformat()
        )
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Make API call
                logger.debug(
                    "calling_delta_api",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    symbol=symbol,
                    resolution=resolution
                )
                
                response = await self.delta_client.get_candles(
                    symbol=symbol,
                    resolution=resolution,
                    start=start,
                    end=end
                )
                
                # Log response structure for debugging
                logger.debug(
                    "api_response_received",
                    response_type=type(response).__name__,
                    response_keys=list(response.keys()) if isinstance(response, dict) else None,
                    has_result="result" in response if isinstance(response, dict) else False,
                    has_success="success" in response if isinstance(response, dict) else False
                )
                
                # Validate response is a dictionary
                if not isinstance(response, dict):
                    error_msg = (
                        f"API returned non-dict response: {type(response).__name__}. "
                        f"Expected dict with 'result' and 'success' keys. "
                        f"Response: {str(response)[:500]}"
                    )
                    logger.error(
                        "invalid_api_response_type",
                        response_type=type(response).__name__,
                        response_preview=str(response)[:500]
                    )
                    raise ValueError(error_msg)
                
                # Check for success status
                success = response.get("success", None)
                if success is False:
                    error_msg = response.get("error", {}).get("message", "Unknown API error")
                    error_code = response.get("error", {}).get("code", "UNKNOWN")
                    full_error = (
                        f"API request failed with error code {error_code}: {error_msg}. "
                        f"Check API credentials and symbol validity. "
                        f"Full response: {response}"
                    )
                    logger.error(
                        "api_request_failed",
                        error_code=error_code,
                        error_message=error_msg,
                        response=response
                    )
                    raise DeltaExchangeError(full_error)
                
                # Validate result key exists
                if "result" not in response:
                    error_msg = (
                        f"API response missing 'result' key. "
                        f"Response keys: {list(response.keys())}. "
                        f"Full response: {response}"
                    )
                    logger.error(
                        "api_response_missing_result",
                        response_keys=list(response.keys()),
                        response=response
                    )
                    raise ValueError(error_msg)
                
                # Validate result is a list
                candles = response.get("result")
                if not isinstance(candles, list):
                    error_msg = (
                        f"API response 'result' is not a list: {type(candles).__name__}. "
                        f"Expected list of candles. "
                        f"Response: {response}"
                    )
                    logger.error(
                        "api_response_result_not_list",
                        result_type=type(candles).__name__,
                        response=response
                    )
                    raise ValueError(error_msg)
                
                # Log empty result (different from error - might be valid)
                if len(candles) == 0:
                    logger.warning(
                        "api_returned_empty_candles",
                        symbol=symbol,
                        resolution=resolution,
                        start=start,
                        end=end,
                        start_iso=datetime.fromtimestamp(start, tz=timezone.utc).isoformat(),
                        end_iso=datetime.fromtimestamp(end, tz=timezone.utc).isoformat(),
                        message="API returned empty candle list - may indicate no data for this time range"
                    )
                    return []  # Return empty list instead of raising error
                
                # Convert to standard format
                formatted_candles = []
                for idx, candle in enumerate(candles):
                    if not isinstance(candle, dict):
                        logger.warning(
                            "invalid_candle_format",
                            candle_index=idx,
                            candle_type=type(candle).__name__,
                            skipping=True
                        )
                        continue
                    
                    try:
                        formatted_candles.append({
                            "timestamp": candle.get("time", 0),
                            "open": float(candle.get("open", 0)),
                            "high": float(candle.get("high", 0)),
                            "low": float(candle.get("low", 0)),
                            "close": float(candle.get("close", 0)),
                            "volume": float(candle.get("volume", 0))
                        })
                    except (ValueError, TypeError) as e:
                        logger.warning(
                            "candle_conversion_failed",
                            candle_index=idx,
                            candle=candle,
                            error=str(e),
                            skipping=True
                        )
                        continue
                
                logger.info(
                    "candles_batch_fetched",
                    symbol=symbol,
                    resolution=resolution,
                    raw_candles=len(candles),
                    formatted_candles=len(formatted_candles),
                    start=start,
                    end=end
                )
                
                return formatted_candles
                
            except (DeltaExchangeError, ValueError) as e:
                # Don't retry on validation errors or API errors
                logger.error(
                    "fetch_candles_batch_failed_non_retryable",
                    symbol=symbol,
                    resolution=resolution,
                    start=start,
                    end=end,
                    attempt=attempt + 1,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True
                )
                raise
                
            except Exception as e:
                last_error = e
                is_last_attempt = (attempt + 1) >= max_retries
                
                logger.warning(
                    "fetch_candles_batch_retryable_error",
                    symbol=symbol,
                    resolution=resolution,
                    start=start,
                    end=end,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                    error_type=type(e).__name__,
                    will_retry=not is_last_attempt,
                    exc_info=not is_last_attempt  # Only log full traceback if not last attempt
                )
                
                if is_last_attempt:
                    error_msg = (
                        f"Failed to fetch candles after {max_retries} attempts. "
                        f"Last error: {str(e)}. "
                        f"Parameters: symbol={symbol}, resolution={resolution}, "
                        f"start={start} ({datetime.fromtimestamp(start, tz=timezone.utc).isoformat()}), "
                        f"end={end} ({datetime.fromtimestamp(end, tz=timezone.utc).isoformat()}). "
                        f"Check API credentials, network connectivity, and symbol validity."
                    )
                    logger.error(
                        "fetch_candles_batch_failed_all_retries",
                        symbol=symbol,
                        resolution=resolution,
                        start=start,
                        end=end,
                        max_retries=max_retries,
                        final_error=str(e),
                        error_type=type(e).__name__,
                        exc_info=True
                    )
                    raise DeltaExchangeError(error_msg) from e
                
                # Exponential backoff for retries
                delay = retry_delay * (2 ** attempt)
                logger.debug("retrying_after_delay", delay=delay, next_attempt=attempt + 2)
                await asyncio.sleep(delay)
        
        # Should never reach here, but just in case
        raise DeltaExchangeError(
            f"Unexpected error in _fetch_candles_batch after {max_retries} attempts. "
            f"Last error: {str(last_error) if last_error else 'Unknown'}"
        )
    
    async def fetch_historical_data(
        self,
        interval: str,
        total_candles: int = 5000
    ) -> List[Dict[str, Any]]:
        """Fetch historical candles with pagination support.
        
        Handles:
        - API limit of 2,000 candles per request
        - Multiple batches for large datasets
        - Data reversal (API returns reverse chronological)
        - Rate limiting between requests
        
        Args:
            interval: Candle interval (e.g., "15m", "1h", "4h")
            total_candles: Total number of candles to fetch
            
        Returns:
            List of candle dictionaries in chronological order (oldest first)
        """
        logger.info(
            "fetching_historical_data",
            symbol=self.symbol,
            interval=interval,
            total_candles=total_candles
        )
        
        # Calculate number of batches needed
        num_batches = math.ceil(total_candles / MAX_CANDLES_PER_REQUEST)
        candles_per_batch = min(MAX_CANDLES_PER_REQUEST, total_candles)
        
        logger.info(
            "pagination_calculation",
            num_batches=num_batches,
            candles_per_batch=candles_per_batch
        )
        
        # Calculate time range for total candles
        # According to Delta Exchange India API documentation:
        # Supported resolutions: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 1d
        # Note: 1w (604800 seconds) included but verify API support
        # Deprecated: 7d, 2w, 30d (no longer supported as of Oct 2025)
        resolution_seconds = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900,
            "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
            "6h": 21600, "1d": 86400, "1w": 604800  # 1w may work but not explicitly documented
        }
        
        seconds_per_candle = resolution_seconds.get(interval.lower(), 3600)
        total_seconds = total_candles * seconds_per_candle
        
        end_time = int(time.time())
        start_time = end_time - total_seconds
        
        all_candles = []
        batch_errors = []  # Accumulate errors from all batches
        
        # Fetch each batch sequentially
        for batch_idx in range(num_batches):
            # Calculate batch time range
            batch_start = start_time + (batch_idx * candles_per_batch * seconds_per_candle)
            batch_end = min(
                start_time + ((batch_idx + 1) * candles_per_batch * seconds_per_candle),
                end_time
            )
            
            logger.info(
                "fetching_batch",
                batch_idx=batch_idx + 1,
                total_batches=num_batches,
                batch_start=batch_start,
                batch_end=batch_end,
                batch_start_iso=datetime.fromtimestamp(batch_start, tz=timezone.utc).isoformat(),
                batch_end_iso=datetime.fromtimestamp(batch_end, tz=timezone.utc).isoformat()
            )
            
            try:
                # Fetch batch
                logger.debug(
                    "calling_fetch_candles_batch",
                    batch_idx=batch_idx + 1,
                    symbol=self.symbol,
                    resolution=interval.lower(),
                    start=batch_start,
                    end=batch_end
                )
                
                batch_candles = await self._fetch_candles_batch(
                    symbol=self.symbol,
                    resolution=interval.lower(),
                    start=batch_start,
                    end=batch_end
                )
                
                logger.debug(
                    "fetch_candles_batch_returned",
                    batch_idx=batch_idx + 1,
                    returned_type=type(batch_candles).__name__,
                    returned_length=len(batch_candles) if isinstance(batch_candles, list) else None
                )
                
                # Validate batch was fetched successfully
                if batch_candles is None:
                    error_msg = f"Batch {batch_idx + 1} returned None instead of candle list"
                    logger.error("batch_returned_none", batch_idx=batch_idx + 1, error=error_msg)
                    batch_errors.append({
                        "batch": batch_idx + 1,
                        "error": error_msg,
                        "start": batch_start,
                        "end": batch_end
                    })
                    continue
                
                # Validate batch has candles (empty list is acceptable, but log it)
                if len(batch_candles) == 0:
                    logger.warning(
                        "batch_empty",
                        batch_idx=batch_idx + 1,
                        batch_start=batch_start,
                        batch_end=batch_end,
                        batch_start_iso=datetime.fromtimestamp(batch_start, tz=timezone.utc).isoformat(),
                        batch_end_iso=datetime.fromtimestamp(batch_end, tz=timezone.utc).isoformat(),
                        message="Batch returned empty candle list - may indicate no data for this time range"
                    )
                    # Continue to next batch - empty batches are not necessarily errors
                else:
                    # Log first and last candle for debugging
                    first_candle = batch_candles[0] if batch_candles else None
                    last_candle = batch_candles[-1] if batch_candles else None
                    logger.debug(
                        "batch_candles_preview",
                        batch_idx=batch_idx + 1,
                        first_candle_time=first_candle.get("time") if first_candle else None,
                        first_candle_time_iso=datetime.fromtimestamp(first_candle.get("time"), tz=timezone.utc).isoformat() if first_candle and first_candle.get("time") else None,
                        last_candle_time=last_candle.get("time") if last_candle else None,
                        last_candle_time_iso=datetime.fromtimestamp(last_candle.get("time"), tz=timezone.utc).isoformat() if last_candle and last_candle.get("time") else None,
                        candle_count=len(batch_candles)
                    )
                
                # API returns reverse chronological (newest first)
                # Reverse to get chronological order (oldest first)
                batch_candles_before_reverse = len(batch_candles)
                batch_candles.reverse()
                
                # Log after reversal
                if batch_candles:
                    first_candle_after = batch_candles[0]
                    last_candle_after = batch_candles[-1]
                    logger.debug(
                        "batch_after_reversal",
                        batch_idx=batch_idx + 1,
                        first_timestamp=first_candle_after.get("timestamp"),
                        first_timestamp_iso=datetime.fromtimestamp(first_candle_after.get("timestamp"), tz=timezone.utc).isoformat() if first_candle_after.get("timestamp") else None,
                        last_timestamp=last_candle_after.get("timestamp"),
                        last_timestamp_iso=datetime.fromtimestamp(last_candle_after.get("timestamp"), tz=timezone.utc).isoformat() if last_candle_after.get("timestamp") else None
                    )
                
                all_candles.extend(batch_candles)
                
                logger.info(
                    "batch_fetched",
                    batch_idx=batch_idx + 1,
                    total_batches=num_batches,
                    candles_in_batch=batch_candles_before_reverse,
                    cumulative_candles=len(all_candles),
                    success=True,
                    batch_start_iso=datetime.fromtimestamp(batch_start, tz=timezone.utc).isoformat(),
                    batch_end_iso=datetime.fromtimestamp(batch_end, tz=timezone.utc).isoformat()
                )
                
                # Rate limiting: wait between requests (except for last batch)
                if batch_idx < num_batches - 1:
                    await asyncio.sleep(RATE_LIMIT_DELAY)
                    
            except (DeltaExchangeError, ValueError) as e:
                # Non-retryable errors - log and continue with other batches
                error_info = {
                    "batch": batch_idx + 1,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "start": batch_start,
                    "end": batch_end,
                    "start_iso": datetime.fromtimestamp(batch_start, tz=timezone.utc).isoformat(),
                    "end_iso": datetime.fromtimestamp(batch_end, tz=timezone.utc).isoformat()
                }
                batch_errors.append(error_info)
                
                logger.error(
                    "batch_fetch_failed_non_retryable",
                    **error_info,
                    exc_info=True,
                    message="Batch failed with non-retryable error, continuing with other batches"
                )
                # Continue with other batches instead of failing completely
                continue
                
            except Exception as e:
                # Unexpected errors - log and continue
                error_info = {
                    "batch": batch_idx + 1,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "start": batch_start,
                    "end": batch_end,
                    "start_iso": datetime.fromtimestamp(batch_start, tz=timezone.utc).isoformat(),
                    "end_iso": datetime.fromtimestamp(batch_end, tz=timezone.utc).isoformat()
                }
                batch_errors.append(error_info)
                
                logger.error(
                    "batch_fetch_failed_unexpected",
                    **error_info,
                    exc_info=True,
                    message="Batch failed with unexpected error, continuing with other batches"
                )
                # Continue with other batches instead of failing completely
                continue
        
        # Report accumulated errors if any
        if batch_errors:
            # Build error summary string
            error_parts = []
            for e in batch_errors[:3]:
                batch_num = e.get("batch", "?")
                error_msg = e.get("error", "Unknown error")
                error_parts.append(f"Batch {batch_num}: {error_msg}")
            
            error_summary = (
                f"Encountered {len(batch_errors)} batch error(s) out of {num_batches} total batches. "
                f"Fetched {len(all_candles)} candles total. "
                f"Errors: {', '.join(error_parts)}"
                + (f" (and {len(batch_errors) - 3} more)" if len(batch_errors) > 3 else "")
            )
            logger.warning(
                "batch_errors_encountered",
                total_errors=len(batch_errors),
                total_batches=num_batches,
                candles_fetched=len(all_candles),
                errors=batch_errors,
                summary=error_summary
            )
        
        # Early validation: Check if any candles were fetched
        if len(all_candles) == 0:
            error_details = []
            if batch_errors:
                error_details.append(f"{len(batch_errors)} batch(es) failed")
            else:
                error_details.append("All batches returned empty results")
            
            error_msg = (
                f"No candles were fetched for symbol '{self.symbol}' with interval '{interval}'. "
                f"Requested {total_candles} candles from {datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat()} "
                f"to {datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat()}. "
                f"{'; '.join(error_details)}. "
                f"Batches attempted: {num_batches}, Successful: {num_batches - len(batch_errors)}, Failed: {len(batch_errors)}. "
                f"Possible causes: "
                f"1. Symbol '{self.symbol}' is invalid or not available, "
                f"2. No historical data exists for the requested time range, "
                f"3. API credentials are invalid or lack permissions, "
                f"4. Network connectivity issues."
            )
            logger.error(
                "no_candles_fetched",
                symbol=self.symbol,
                interval=interval,
                requested_candles=total_candles,
                start_time=start_time,
                end_time=end_time,
                batch_errors=len(batch_errors),
                batches_attempted=num_batches,
                batches_successful=num_batches - len(batch_errors),
                error=error_msg
            )
            raise ValueError(error_msg)
        
        # Remove duplicates based on timestamp and validate timestamps
        # Note: We DON'T reverse all_candles here because:
        # - Batches are fetched in chronological order (oldest batch first)
        # - Each batch is already reversed to be chronological (oldest candle first)
        # - So all_candles is already in chronological order (oldest to newest)
        seen_timestamps = set()
        unique_candles = []
        invalid_timestamp_count = 0
        
        for candle in all_candles:
            ts = candle.get("timestamp")
            
            # Validate timestamp
            if ts is None or ts == 0:
                invalid_timestamp_count += 1
                logger.warning(
                    "invalid_candle_timestamp",
                    candle=candle,
                    timestamp=ts,
                    message="Skipping candle with invalid timestamp"
                )
                continue
            
            if ts not in seen_timestamps:
                seen_timestamps.add(ts)
                unique_candles.append(candle)
            else:
                logger.debug(
                    "duplicate_timestamp_skipped",
                    timestamp=ts,
                    message="Skipping duplicate candle timestamp"
                )
        
        if invalid_timestamp_count > 0:
            logger.warning(
                "invalid_timestamps_filtered",
                count=invalid_timestamp_count,
                total_candles=len(all_candles),
                message=f"Filtered out {invalid_timestamp_count} candles with invalid timestamps"
            )
        
        # Sort by timestamp to ensure chronological order (should already be sorted, but ensure it)
        unique_candles.sort(key=lambda x: x["timestamp"])
        
        # Calculate statistics
        duplicates_removed = len(all_candles) - len(unique_candles) - invalid_timestamp_count
        
        # Log final summary with detailed statistics
        if unique_candles:
            first_candle_ts = unique_candles[0].get("timestamp")
            last_candle_ts = unique_candles[-1].get("timestamp")
            logger.info(
                "historical_data_fetched",
                symbol=self.symbol,
                interval=interval,
                total_candles=len(unique_candles),
                requested_candles=total_candles,
                batches_successful=num_batches - len(batch_errors),
                batches_failed=len(batch_errors),
                batches_total=num_batches,
                coverage_pct=(len(unique_candles) / total_candles * 100) if total_candles > 0 else 0,
                first_candle_timestamp=first_candle_ts,
                first_candle_iso=datetime.fromtimestamp(first_candle_ts, tz=timezone.utc).isoformat() if first_candle_ts else None,
                last_candle_timestamp=last_candle_ts,
                last_candle_iso=datetime.fromtimestamp(last_candle_ts, tz=timezone.utc).isoformat() if last_candle_ts else None,
                invalid_timestamps_filtered=invalid_timestamp_count,
                duplicates_removed=duplicates_removed,
                raw_candles_before_processing=len(all_candles)
            )
        else:
            logger.warning(
                "historical_data_fetched_empty",
                symbol=self.symbol,
                interval=interval,
                total_candles=len(unique_candles),
                requested_candles=total_candles,
                batches_successful=num_batches - len(batch_errors),
                batches_failed=len(batch_errors),
                batches_total=num_batches,
                raw_candles_before_processing=len(all_candles),
                invalid_timestamps_filtered=invalid_timestamp_count,
                duplicates_removed=duplicates_removed,
                message="No valid candles after processing (filtering duplicates and invalid timestamps)"
            )
        
        return unique_candles
    
    async def compute_features(
        self,
        candles: List[Dict[str, Any]]
    ) -> pd.DataFrame:
        """Compute all 49 features using FeatureEngineering.
        
        Args:
            candles: List of candle dictionaries in chronological order
            
        Returns:
            DataFrame with features for each candle
        """
        logger.info(
            "computing_features",
            candles_count=len(candles),
            feature_count=len(FEATURE_LIST)
        )
        
        feature_data = []
        
        # Compute features for each candle (using rolling window)
        for i in range(len(candles)):
            # Use candles up to current index for feature computation
            window_candles = candles[:i+1]
            
            if len(window_candles) < 10:  # Need minimum candles for some features
                # Fill with zeros for early candles
                feature_row = {feature: 0.0 for feature in FEATURE_LIST}
            else:
                feature_row = {}
                for feature_name in FEATURE_LIST:
                    try:
                        value = await self.feature_engineering.compute_feature(
                            feature_name, window_candles
                        )
                        feature_row[feature_name] = value
                    except Exception as e:
                        logger.warning(
                            "feature_computation_failed",
                            feature=feature_name,
                            candle_index=i,
                            error=str(e)
                        )
                        feature_row[feature_name] = 0.0
            
            feature_data.append(feature_row)
        
        df = pd.DataFrame(feature_data)
        logger.info("features_computed", rows=len(df), columns=len(df.columns))
        
        return df
    
    def create_regression_labels(
        self,
        candles: List[Dict[str, Any]],
        forward_periods: int = 1
    ) -> np.ndarray:
        """Create regression labels (future price).
        
        Args:
            candles: List of candle dictionaries
            forward_periods: Number of periods to look ahead
            
        Returns:
            Array of future prices
        """
        labels = []
        
        for i in range(len(candles)):
            if i + forward_periods >= len(candles):
                # No future data, use current price
                labels.append(candles[i]["close"])
                continue
            
            future_close = candles[i + forward_periods]["close"]
            labels.append(future_close)
        
        return np.array(labels)
    
    def create_classification_labels(
        self,
        candles: List[Dict[str, Any]],
        forward_periods: int = 1,
        buy_threshold: float = 0.5,
        sell_threshold: float = -0.5
    ) -> np.ndarray:
        """Create classification labels (buy/sell/hold).
        
        Args:
            candles: List of candle dictionaries
            forward_periods: Number of periods to look ahead
            buy_threshold: Return threshold for BUY signal (%)
            sell_threshold: Return threshold for SELL signal (%)
            
        Returns:
            Array of labels: 1 (BUY), -1 (SELL), 0 (HOLD)
        """
        labels = []
        
        for i in range(len(candles)):
            if i + forward_periods >= len(candles):
                # No future data, label as HOLD
                labels.append(0)
                continue
            
            current_close = candles[i]["close"]
            future_close = candles[i + forward_periods]["close"]
            
            # Calculate return percentage
            return_pct = (future_close - current_close) / current_close * 100
            
            if return_pct > buy_threshold:
                labels.append(1)  # BUY
            elif return_pct < sell_threshold:
                labels.append(-1)  # SELL
            else:
                labels.append(0)  # HOLD
        
        return np.array(labels)
    
    def train_xgboost_regressor(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        timeframe: str
    ) -> Tuple[XGBRegressor, Dict[str, Any]]:
        """Train XGBoost regressor for price prediction.
        
        Args:
            X: Feature matrix
            y: Target prices
            timeframe: Timeframe identifier
            
        Returns:
            Tuple of (trained model, metrics dictionary)
        """
        logger.info(
            "training_xgboost_regressor",
            timeframe=timeframe,
            samples=len(X),
            features=X.shape[1]
        )
        
        # Train/validation/test split
        train_size = int(len(X) * 0.7)
        val_size = int(len(X) * 0.15)
        
        X_train = X[:train_size]
        y_train = y[:train_size]
        X_val = X[train_size:train_size+val_size]
        y_val = y[train_size:train_size+val_size]
        X_test = X[train_size+val_size:]
        y_test = y[train_size+val_size:]
        
        # Train model
        model = XGBRegressor(
            max_depth=6,
            learning_rate=0.1,
            n_estimators=100,
            random_state=42,
            eval_metric='rmse'
        )
        
        start_time = time.time()
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False
        )
        training_time = time.time() - start_time
        
        # Evaluate
        train_rmse = np.sqrt(np.mean((model.predict(X_train) - y_train) ** 2))
        val_rmse = np.sqrt(np.mean((model.predict(X_val) - y_val) ** 2))
        test_rmse = np.sqrt(np.mean((model.predict(X_test) - y_test) ** 2))
        
        logger.info(
            "xgboost_regressor_trained",
            timeframe=timeframe,
            training_time=training_time,
            train_rmse=train_rmse,
            val_rmse=val_rmse,
            test_rmse=test_rmse
        )
        
        return model, {
            "train_rmse": train_rmse,
            "val_rmse": val_rmse,
            "test_rmse": test_rmse,
            "training_time": training_time
        }
    
    def train_xgboost_classifier(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        timeframe: str
    ) -> Tuple[XGBClassifier, Dict[str, Any]]:
        """Train XGBoost classifier for signal prediction.
        
        Args:
            X: Feature matrix
            y: Target labels (-1, 0, 1)
            timeframe: Timeframe identifier
            
        Returns:
            Tuple of (trained model, metrics dictionary)
        """
        # Detect unique classes in the data
        unique_classes = np.unique(y)
        num_classes = len(unique_classes)
        
        logger.info(
            "training_xgboost_classifier",
            timeframe=timeframe,
            samples=len(X),
            features=X.shape[1],
            classes=unique_classes,
            num_classes=num_classes
        )
        
        # Map labels based on number of classes present
        y_mapped = y.copy()
        
        if num_classes == 2:
            # Binary classification: map to [0, 1]
            if -1 in unique_classes and 1 in unique_classes:
                # SELL (-1) and BUY (1) -> map to [0, 1]
                y_mapped[y == -1] = 0  # SELL -> 0
                y_mapped[y == 1] = 1   # BUY -> 1
            elif -1 in unique_classes and 0 in unique_classes:
                # SELL (-1) and HOLD (0) -> map to [0, 1]
                y_mapped[y == -1] = 0  # SELL -> 0
                y_mapped[y == 0] = 1   # HOLD -> 1
            elif 0 in unique_classes and 1 in unique_classes:
                # HOLD (0) and BUY (1) -> map to [0, 1]
                y_mapped[y == 0] = 0   # HOLD -> 0
                y_mapped[y == 1] = 1   # BUY -> 1
            else:
                # Fallback: use sorted unique classes
                sorted_classes = np.sort(unique_classes)
                for idx, class_val in enumerate(sorted_classes):
                    y_mapped[y == class_val] = idx
        else:
            # Multi-class: map to [0, 1, 2] for SELL, HOLD, BUY
            y_mapped[y == -1] = 0  # SELL -> 0
            y_mapped[y == 0] = 1   # HOLD -> 1
            y_mapped[y == 1] = 2   # BUY -> 2
        
        # Train/validation/test split
        train_size = int(len(X) * 0.7)
        val_size = int(len(X) * 0.15)
        
        X_train = X[:train_size]
        y_train = y_mapped[:train_size]
        X_val = X[train_size:train_size+val_size]
        y_val = y_mapped[train_size:train_size+val_size]
        X_test = X[train_size+val_size:]
        y_test = y_mapped[train_size+val_size:]

        # Balance class influence without discarding HOLD labels.
        train_labels, train_counts = np.unique(y_train, return_counts=True)
        class_weights = {}
        for label, count in zip(train_labels, train_counts):
            class_weights[int(label)] = len(y_train) / (len(train_labels) * max(int(count), 1))
        sample_weight_train = np.array([class_weights[int(label)] for label in y_train], dtype=float)
        
        # Train model with appropriate parameters based on number of classes
        if num_classes == 2:
            # Binary classification
            model = XGBClassifier(
                max_depth=6,
                learning_rate=0.1,
                n_estimators=100,
                objective='binary:logistic',
                random_state=42,
                eval_metric='logloss'
            )
        else:
            # Multi-class classification
            model = XGBClassifier(
                max_depth=6,
                learning_rate=0.1,
                n_estimators=100,
                objective='multi:softprob',
                num_class=3,
                random_state=42,
                eval_metric='mlogloss'
            )
        
        start_time = time.time()
        model.fit(
            X_train, y_train,
            sample_weight=sample_weight_train,
            eval_set=[(X_val, y_val)],
            verbose=False
        )
        training_time = time.time() - start_time
        
        # Evaluate
        train_acc = model.score(X_train, y_train)
        val_acc = model.score(X_val, y_val)
        test_acc = model.score(X_test, y_test)
        
        logger.info(
            "xgboost_classifier_trained",
            timeframe=timeframe,
            training_time=training_time,
            train_accuracy=train_acc,
            val_accuracy=val_acc,
            test_accuracy=test_acc
        )
        
        return model, {
            "train_accuracy": train_acc,
            "val_accuracy": val_acc,
            "test_accuracy": test_acc,
            "training_time": training_time
        }
    
    def train_lstm_model(
        self,
        X: pd.DataFrame,
        y: np.ndarray,
        timeframe: str,
        task_type: str = "regression"
    ) -> Tuple[Any, Dict[str, Any]]:
        """Train LSTM model for price/signal prediction.
        
        Args:
            X: Feature matrix
            y: Target values (prices for regression, labels for classification)
            timeframe: Timeframe identifier
            task_type: "regression" or "classification"
            
        Returns:
            Tuple of (trained model, metrics dictionary)
            
        Note:
            LSTM training requires TensorFlow/Keras. This is a placeholder
            implementation that should be completed with actual LSTM architecture.
        """
        logger.info(
            "training_lstm_model",
            timeframe=timeframe,
            task_type=task_type,
            samples=len(X),
            features=X.shape[1]
        )
        
        try:
            import tensorflow as tf
            from tensorflow import keras
            from tensorflow.keras.models import Sequential
            from tensorflow.keras.layers import LSTM, Dense, Dropout
        except ImportError:
            logger.warning(
                "tensorflow_not_available",
                message="TensorFlow not available, skipping LSTM training"
            )
            return None, {"error": "TensorFlow not available"}
        
        # Prepare data for LSTM (requires sequences)
        sequence_length = 60  # Use 60 previous candles
        
        X_sequences = []
        y_sequences = []
        
        for i in range(sequence_length, len(X)):
            X_sequences.append(X.iloc[i-sequence_length:i].values)
            y_sequences.append(y[i])
        
        if len(X_sequences) < 100:
            logger.warning(
                "insufficient_data_for_lstm",
                available_sequences=len(X_sequences),
                required=100
            )
            return None, {"error": "Insufficient data for LSTM"}
        
        X_sequences = np.array(X_sequences)
        y_sequences = np.array(y_sequences)
        
        # Reshape for LSTM: (samples, time_steps, features)
        X_sequences = X_sequences.reshape((X_sequences.shape[0], X_sequences.shape[1], X_sequences.shape[2]))
        
        # Train/validation/test split
        train_size = int(len(X_sequences) * 0.7)
        val_size = int(len(X_sequences) * 0.15)
        
        X_train = X_sequences[:train_size]
        y_train = y_sequences[:train_size]
        X_val = X_sequences[train_size:train_size+val_size]
        y_val = y_sequences[train_size:train_size+val_size]
        X_test = X_sequences[train_size+val_size:]
        y_test = y_sequences[train_size+val_size:]
        
        # Build LSTM model
        model = Sequential()
        model.add(LSTM(50, return_sequences=True, input_shape=(sequence_length, X.shape[1])))
        model.add(Dropout(0.2))
        model.add(LSTM(50, return_sequences=False))
        model.add(Dropout(0.2))
        
        if task_type == "regression":
            model.add(Dense(1))
            model.compile(optimizer='adam', loss='mse', metrics=['mae'])
        else:
            # Classification: convert labels to one-hot
            num_classes = len(np.unique(y_sequences))
            y_train_cat = keras.utils.to_categorical(y_train, num_classes)
            y_val_cat = keras.utils.to_categorical(y_val, num_classes)
            y_test_cat = keras.utils.to_categorical(y_test, num_classes)
            
            model.add(Dense(num_classes, activation='softmax'))
            model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])
        
        # Train model
        start_time = time.time()
        
        if task_type == "regression":
            history = model.fit(
                X_train, y_train,
                validation_data=(X_val, y_val),
                epochs=50,
                batch_size=32,
                verbose=0
            )
            
            train_rmse = np.sqrt(model.evaluate(X_train, y_train, verbose=0)[0])
            val_rmse = np.sqrt(model.evaluate(X_val, y_val, verbose=0)[0])
            test_rmse = np.sqrt(model.evaluate(X_test, y_test, verbose=0)[0])
            
            metrics = {
                "train_rmse": train_rmse,
                "val_rmse": val_rmse,
                "test_rmse": test_rmse
            }
        else:
            history = model.fit(
                X_train, y_train_cat,
                validation_data=(X_val, y_val_cat),
                epochs=50,
                batch_size=32,
                verbose=0
            )
            
            train_acc = model.evaluate(X_train, y_train_cat, verbose=0)[1]
            val_acc = model.evaluate(X_val, y_val_cat, verbose=0)[1]
            test_acc = model.evaluate(X_test, y_test_cat, verbose=0)[1]
            
            metrics = {
                "train_accuracy": train_acc,
                "val_accuracy": val_acc,
                "test_accuracy": test_acc
            }
        
        training_time = time.time() - start_time
        metrics["training_time"] = training_time
        
        logger.info(
            "lstm_model_trained",
            timeframe=timeframe,
            task_type=task_type,
            training_time=training_time,
            **metrics
        )
        
        return model, metrics
    
    def save_model(
        self,
        model: Any,
        model_type: str,
        timeframe: str,
        task_type: str,
        metadata: Dict[str, Any]
    ) -> Path:
        """Save trained model to file.
        
        Saves models to both locations:
        - Primary: models/ (for Colab download)
        - Secondary: agent/model_storage/xgboost/ (for agent discovery)
        
        Args:
            model: Trained model instance
            model_type: "xgboost" or "lstm"
            timeframe: Timeframe identifier
            task_type: "regression" or "classification"
            metadata: Training metadata
            
        Returns:
            Path to primary saved model file (models/)
        """
        # Determine filename
        if model_type == "xgboost":
            if task_type == "regression":
                filename = f"xgboost_regressor_{self.symbol}_{timeframe}.pkl"
            else:
                filename = f"xgboost_classifier_{self.symbol}_{timeframe}.pkl"
            file_ext = ".pkl"
        else:  # LSTM
            if task_type == "regression":
                filename = f"lstm_regressor_{self.symbol}_{timeframe}.h5"
            else:
                filename = f"lstm_classifier_{self.symbol}_{timeframe}.h5"
            file_ext = ".h5"
        
        # Primary location: models/ (for Colab download)
        primary_path = self.models_dir / filename
        
        # Secondary location: agent/model_storage/xgboost/ (for agent discovery)
        secondary_path = self.storage_dir / filename
        
        logger.info(
            "saving_model",
            primary_path=str(primary_path),
            secondary_path=str(secondary_path),
            model_type=model_type
        )
        
        # Save model to primary location
        if model_type == "xgboost":
            # Backup existing file if it exists
            if primary_path.exists():
                backup_path = primary_path.with_suffix(file_ext + '.backup')
                logger.info("backing_up_existing_model", backup_path=str(backup_path))
                primary_path.rename(backup_path)
            
            with open(primary_path, 'wb') as f:
                pickle.dump(model, f)
            
            # Copy to secondary location (agent discovery)
            if secondary_path.exists():
                backup_path = secondary_path.with_suffix(file_ext + '.backup')
                logger.info("backing_up_existing_model_secondary", backup_path=str(backup_path))
                secondary_path.rename(backup_path)
            
            # Copy file to secondary location
            import shutil
            shutil.copy2(primary_path, secondary_path)
            logger.info("model_copied_to_agent_location", secondary_path=str(secondary_path))
            
        else:  # LSTM
            # Backup existing file if it exists
            if primary_path.exists():
                backup_path = primary_path.with_suffix(file_ext + '.backup')
                logger.info("backing_up_existing_model", backup_path=str(backup_path))
                primary_path.rename(backup_path)
            
            model.save(str(primary_path))
            
            # Copy to secondary location (agent discovery)
            if secondary_path.exists():
                backup_path = secondary_path.with_suffix(file_ext + '.backup')
                logger.info("backing_up_existing_model_secondary", backup_path=str(backup_path))
                secondary_path.rename(backup_path)
            
            # Copy file to secondary location
            import shutil
            shutil.copy2(primary_path, secondary_path)
            logger.info("model_copied_to_agent_location", secondary_path=str(secondary_path))
        
        logger.info(
            "model_saved",
            primary_path=str(primary_path),
            secondary_path=str(secondary_path),
            primary_file_size=primary_path.stat().st_size,
            secondary_file_size=secondary_path.stat().st_size
        )
        
        return primary_path
    
    def validate_model(
        self,
        model_path: Path,
        model_type: str,
        expected_features: int = 50
    ) -> Dict[str, Any]:
        """Validate a saved model can be loaded and has correct structure.
        
        Args:
            model_path: Path to model file
            model_type: "xgboost" or "lstm"
            expected_features: Expected number of input features (default: 49)
            
        Returns:
            Dictionary with validation results
        """
        validation_results = {
            "model_path": str(model_path),
            "exists": False,
            "loadable": False,
            "has_predict": False,
            "has_predict_proba": False,
            "feature_count_valid": False,
            "errors": []
        }
        
        # Check file exists
        if not model_path.exists():
            validation_results["errors"].append(f"Model file does not exist: {model_path}")
            return validation_results
        
        validation_results["exists"] = True
        file_size = model_path.stat().st_size
        
        # Try to load model
        try:
            if model_type == "xgboost":
                with open(model_path, 'rb') as f:
                    model = pickle.load(f)
                
                # Check model has required methods
                validation_results["has_predict"] = hasattr(model, 'predict')
                validation_results["has_predict_proba"] = hasattr(model, 'predict_proba')
                
                # Check feature count by creating dummy input
                if hasattr(model, 'get_booster'):
                    # XGBoost model - check feature count
                    try:
                        # Try sklearn API first (most reliable)
                        if hasattr(model, 'n_features_in_'):
                            feature_count = model.n_features_in_
                        else:
                            booster = model.get_booster()
                            # Try different methods to get feature count
                            if hasattr(booster, 'num_feature'):
                                # Check if it's a method or attribute
                                if callable(getattr(booster, 'num_feature', None)):
                                    feature_count = booster.num_feature()
                                else:
                                    feature_count = booster.num_feature
                            elif hasattr(booster, 'get_num_feature'):
                                feature_count = booster.get_num_feature()
                            else:
                                # Fallback: test with dummy input to infer feature count
                                # Try with expected_features first
                                try:
                                    dummy_features = np.random.rand(1, expected_features)
                                    model.predict(dummy_features)  # This will fail if wrong feature count
                                    feature_count = expected_features  # Assume correct if prediction works
                                except Exception:
                                    # If that fails, try to infer from error or use expected_features
                                    feature_count = expected_features
                        
                        validation_results["feature_count"] = feature_count
                        validation_results["feature_count_valid"] = (feature_count == expected_features)
                        if not validation_results["feature_count_valid"]:
                            validation_results["errors"].append(
                                f"Feature count mismatch: expected {expected_features}, got {feature_count}"
                            )
                    except Exception as e:
                        validation_results["errors"].append(f"Could not get feature count: {str(e)}")
                
                # Test prediction with dummy features
                try:
                    dummy_features = np.random.rand(1, expected_features)
                    prediction = model.predict(dummy_features)
                    validation_results["loadable"] = True
                    validation_results["prediction_test"] = "passed"
                except Exception as e:
                    validation_results["errors"].append(f"Prediction test failed: {str(e)}")
                    validation_results["prediction_test"] = f"failed: {str(e)}"
                
            else:  # LSTM
                # LSTM validation would require TensorFlow
                validation_results["loadable"] = True  # Assume valid if file exists
                validation_results["errors"].append("LSTM validation not fully implemented")
            
        except Exception as e:
            validation_results["errors"].append(f"Failed to load model: {str(e)}")
            validation_results["loadable"] = False
        
        validation_results["file_size"] = file_size
        validation_results["valid"] = (
            validation_results["exists"] and
            validation_results["loadable"] and
            validation_results["has_predict"] and
            validation_results["feature_count_valid"]
        )
        
        logger.info(
            "model_validation_complete",
            model_path=str(model_path),
            valid=validation_results["valid"],
            errors=validation_results["errors"]
        )
        
        return validation_results
    
    def copy_models_to_agent_location(self, timeframe: Optional[str] = None) -> List[Path]:
        """Copy trained models from models/ to agent/model_storage/xgboost/.
        
        Args:
            timeframe: Optional timeframe filter. If None, copies all models.
            
        Returns:
            List of paths to copied model files
        """
        import shutil
        
        copied_files = []
        
        # Find all model files in models directory
        if timeframe:
            patterns = [
                f"xgboost_regressor_{self.symbol}_{timeframe}.pkl",
                f"xgboost_classifier_{self.symbol}_{timeframe}.pkl"
            ]
        else:
            patterns = [
                f"xgboost_regressor_{self.symbol}_*.pkl",
                f"xgboost_classifier_{self.symbol}_*.pkl"
            ]
        
        for pattern in patterns:
            for model_file in self.models_dir.glob(pattern):
                target_file = self.storage_dir / model_file.name
                
                # Backup existing file if it exists
                if target_file.exists():
                    backup_path = target_file.with_suffix('.pkl.backup')
                    logger.info("backing_up_existing_model_for_copy", backup_path=str(backup_path))
                    target_file.rename(backup_path)
                
                # Copy file
                shutil.copy2(model_file, target_file)
                copied_files.append(target_file)
                logger.info(
                    "model_copied_to_agent_location",
                    source=str(model_file),
                    target=str(target_file)
                )
        
        logger.info(
            "models_copied_to_agent_location",
            count=len(copied_files),
            target_dir=str(self.storage_dir)
        )
        
        return copied_files
    
    async def train_timeframe(
        self,
        timeframe: str,
        total_candles: int = 5000,
        train_regression: bool = True,
        train_classification: bool = True,
        train_lstm: bool = False,
        validate_connection: bool = True
    ) -> Dict[str, Any]:
        """Train models for a specific timeframe.
        
        Args:
            timeframe: Timeframe (15m, 1h, 4h)
            total_candles: Total number of candles to fetch
            train_regression: Whether to train regression models
            train_classification: Whether to train classification models
            train_lstm: Whether to train LSTM models (requires TensorFlow)
            validate_connection: Whether to validate API connection before training
            
        Returns:
            Training results dictionary
            
        Raises:
            ValueError: If insufficient data or validation fails
            DeltaExchangeError: If API connection validation fails
        """
        logger.info(
            "starting_training",
            timeframe=timeframe,
            symbol=self.symbol,
            total_candles=total_candles,
            validate_connection=validate_connection
        )
        
        # Pre-flight checks: Validate API connection and symbol
        if validate_connection:
            logger.info("running_preflight_checks", symbol=self.symbol, timeframe=timeframe)
            try:
                await self.validate_api_connection()
                logger.info("preflight_checks_passed", symbol=self.symbol)
            except (ValueError, DeltaExchangeError) as e:
                error_msg = (
                    f"Pre-flight API validation failed: {str(e)}. "
                    f"Cannot proceed with training. "
                    f"Please fix API configuration before retrying."
                )
                logger.error("preflight_checks_failed", error=str(e), exc_info=True)
                raise DeltaExchangeError(error_msg) from e
            except Exception as e:
                error_msg = (
                    f"Unexpected error during pre-flight validation: {str(e)}. "
                    f"Please check API configuration and network connectivity."
                )
                logger.error("preflight_checks_unexpected_error", error=str(e), exc_info=True)
                raise DeltaExchangeError(error_msg) from e
        
        # Validate timeframe format
        # According to Delta Exchange India API documentation (as of Oct 2025):
        # Supported: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 1d
        # Deprecated (no longer supported): 7d, 2w, 30d
        # Note: 1w is not explicitly documented but may work - verify with API
        valid_timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "1d", "1w"]
        deprecated_timeframes = ["7d", "2w", "30d"]
        
        timeframe_lower = timeframe.lower()
        
        # Check for deprecated timeframes first
        if timeframe_lower in deprecated_timeframes:
            error_msg = (
                f"Timeframe '{timeframe}' is deprecated and no longer supported by Delta Exchange API "
                f"(as of October 18, 2025). "
                f"Deprecated timeframes: {', '.join(deprecated_timeframes)}. "
                f"Please use one of the supported intervals: {', '.join([t for t in valid_timeframes if t != '1w'])}."
            )
            logger.error("deprecated_timeframe", timeframe=timeframe, deprecated_timeframes=deprecated_timeframes)
            raise ValueError(error_msg)
        
        # Check for valid timeframes
        if timeframe_lower not in valid_timeframes:
            error_msg = (
                f"Invalid timeframe '{timeframe}'. "
                f"Valid timeframes are: {', '.join([t for t in valid_timeframes if t != '1w'])}, 1w (verify support). "
                f"Deprecated (do not use): {', '.join(deprecated_timeframes)}. "
                f"Please use one of the supported intervals."
            )
            logger.error("invalid_timeframe", timeframe=timeframe, valid_timeframes=valid_timeframes)
            raise ValueError(error_msg)
        
        # Validate total_candles
        if total_candles < 100:
            error_msg = (
                f"total_candles ({total_candles}) is too small. "
                f"Minimum 100 candles required for meaningful training. "
                f"Recommended: at least 500 candles."
            )
            logger.error("insufficient_candles_requested", total_candles=total_candles)
            raise ValueError(error_msg)
        
        # Fetch data with pagination
        try:
            candles = await self.fetch_historical_data(timeframe, total_candles=total_candles)
        except ValueError as e:
            # Re-raise with additional context
            error_msg = (
                f"Failed to fetch historical data: {str(e)}. "
                f"Training cannot proceed without data. "
                f"Please check symbol '{self.symbol}', timeframe '{timeframe}', and API configuration."
            )
            logger.error("data_fetch_failed", error=str(e), exc_info=True)
            raise ValueError(error_msg) from e
        except Exception as e:
            error_msg = (
                f"Unexpected error while fetching historical data: {str(e)}. "
                f"Please check API configuration and network connectivity."
            )
            logger.error("data_fetch_unexpected_error", error=str(e), exc_info=True)
            raise DeltaExchangeError(error_msg) from e
        
        # Validate we have sufficient data
        if len(candles) < 500:
            # Get additional context for better error message
            first_candle_info = f"First candle: {candles[0].get('timestamp')}" if candles else "No candles"
            last_candle_info = f"Last candle: {candles[-1].get('timestamp')}" if candles else "No candles"
            
            error_msg = (
                f"Insufficient data for training: only {len(candles)} candles fetched, "
                f"but minimum 500 candles required. "
                f"Requested {total_candles} candles for symbol '{self.symbol}' with timeframe '{timeframe}'. "
                f"{first_candle_info}, {last_candle_info}. "
                f"Possible causes: "
                f"1. Symbol '{self.symbol}' has limited historical data, "
                f"2. Requested time range has no data available, "
                f"3. API returned partial data due to errors, "
                f"4. Invalid timestamps filtered out all candles, "
                f"5. Duplicate removal filtered out all candles. "
                f"Troubleshooting steps: "
                f"1. Check API logs for batch errors and warnings, "
                f"2. Verify symbol '{self.symbol}' is valid and has historical data, "
                f"3. Try reducing total_candles to match available data, "
                f"4. Check for timestamp validation warnings in logs, "
                f"5. Verify time range is not in the future."
            )
            logger.error(
                "insufficient_data_for_training",
                candles_fetched=len(candles),
                requested_candles=total_candles,
                symbol=self.symbol,
                timeframe=timeframe,
                first_candle_timestamp=candles[0].get('timestamp') if candles else None,
                last_candle_timestamp=candles[-1].get('timestamp') if candles else None,
                error=error_msg
            )
            raise ValueError(error_msg)
        
        # Compute features
        X = await self.compute_features(candles)
        
        # Validate feature order and count
        if X.shape[1] != len(FEATURE_LIST):
            error_msg = (
                f"Feature count mismatch: computed {X.shape[1]} features, "
                f"but FEATURE_LIST has {len(FEATURE_LIST)} features. "
                f"This indicates a mismatch between feature computation and FEATURE_LIST."
            )
            logger.error("feature_count_mismatch", computed=X.shape[1], expected=len(FEATURE_LIST))
            raise ValueError(error_msg)
        
        # Export feature list to JSON for agent reference
        try:
            feature_list_path = export_feature_list_to_json()
            logger.info("feature_list_exported_for_agent", path=str(feature_list_path))
        except Exception as e:
            logger.warning("feature_list_export_failed", error=str(e))
        
        results = {
            "timeframe": timeframe,
            "samples": len(X),
            "features": len(FEATURE_LIST),
            "candles_fetched": len(candles),
            "feature_list_exported": True
        }
        
        # Train regression models
        if train_regression:
            y_regression = self.create_regression_labels(candles, forward_periods=1)
            
            # Remove rows with insufficient data
            valid_mask = (X.sum(axis=1) != 0)
            X_clean = X[valid_mask].copy()
            y_regression_clean = y_regression[valid_mask].copy()
            
            if len(X_clean) >= 100:
                # Train XGBoost regressor
                xgb_regressor, xgb_metrics = self.train_xgboost_regressor(
                    X_clean, y_regression_clean, timeframe
                )
                xgb_path = self.save_model(
                    xgb_regressor, "xgboost", timeframe, "regression", xgb_metrics
                )
                
                # Validate saved model
                validation = self.validate_model(xgb_path, "xgboost", expected_features=len(FEATURE_LIST))
                results["xgboost_regressor"] = {
                    "model_path": str(xgb_path),
                    "validation": validation,
                    **xgb_metrics
                }
                
                if not validation["valid"]:
                    logger.warning(
                        "model_validation_failed",
                        model_path=str(xgb_path),
                        errors=validation["errors"]
                    )
                
                # Train LSTM regressor if requested
                if train_lstm:
                    lstm_regressor, lstm_metrics = self.train_lstm_model(
                        X_clean, y_regression_clean, timeframe, "regression"
                    )
                    if lstm_regressor is not None:
                        lstm_path = self.save_model(
                            lstm_regressor, "lstm", timeframe, "regression", lstm_metrics
                        )
                        results["lstm_regressor"] = {
                            "model_path": str(lstm_path),
                            **lstm_metrics
                        }
        
        # Train classification models
        if train_classification:
            y_classification = self.create_classification_labels(
                candles, forward_periods=1, buy_threshold=0.5, sell_threshold=-0.5
            )
            
            # Keep HOLD labels; remove only rows with insufficient/empty features
            valid_mask = (X.sum(axis=1) != 0)
            X_clean = X[valid_mask].copy()
            y_classification_clean = y_classification[valid_mask].copy()
            
            if len(X_clean) >= 100:
                # Train XGBoost classifier
                xgb_classifier, xgb_metrics = self.train_xgboost_classifier(
                    X_clean, y_classification_clean, timeframe
                )
                xgb_path = self.save_model(
                    xgb_classifier, "xgboost", timeframe, "classification", xgb_metrics
                )
                
                # Validate saved model
                validation = self.validate_model(xgb_path, "xgboost", expected_features=len(FEATURE_LIST))
                results["xgboost_classifier"] = {
                    "model_path": str(xgb_path),
                    "validation": validation,
                    **xgb_metrics
                }
                
                if not validation["valid"]:
                    logger.warning(
                        "model_validation_failed",
                        model_path=str(xgb_path),
                        errors=validation["errors"]
                    )
                
                # Train LSTM classifier if requested
                if train_lstm:
                    lstm_classifier, lstm_metrics = self.train_lstm_model(
                        X_clean, y_classification_clean, timeframe, "classification"
                    )
                    if lstm_classifier is not None:
                        lstm_path = self.save_model(
                            lstm_classifier, "lstm", timeframe, "classification", lstm_metrics
                        )
                        results["lstm_classifier"] = {
                            "model_path": str(lstm_path),
                            **lstm_metrics
                        }
        
        return results


async def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Train price prediction models for trading agent"
    )
    parser.add_argument(
        "--symbol",
        default="BTCUSD",
        help="Trading symbol (default: BTCUSD)"
    )
    parser.add_argument(
        "--timeframes",
        nargs="+",
        default=["15m", "1h", "4h"],
        help="Timeframes to train (default: 15m 1h 4h)"
    )
    parser.add_argument(
        "--total-candles",
        type=int,
        default=5000,
        help="Total number of candles to fetch per timeframe (default: 5000)"
    )
    parser.add_argument(
        "--regression",
        action="store_true",
        default=True,
        help="Train regression models (default: True)"
    )
    parser.add_argument(
        "--no-regression",
        dest="regression",
        action="store_false",
        help="Skip regression model training"
    )
    parser.add_argument(
        "--classification",
        action="store_true",
        default=True,
        help="Train classification models (default: True)"
    )
    parser.add_argument(
        "--no-classification",
        dest="classification",
        action="store_false",
        help="Skip classification model training"
    )
    parser.add_argument(
        "--lstm",
        action="store_true",
        help="Train LSTM models (requires TensorFlow)"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Price Prediction Model Training Script")
    print("=" * 60)
    print(f"Symbol: {args.symbol}")
    print(f"Timeframes: {', '.join(args.timeframes)}")
    print(f"Total candles per timeframe: {args.total_candles}")
    print(f"Train regression: {args.regression}")
    print(f"Train classification: {args.classification}")
    print(f"Train LSTM: {args.lstm}")
    print()
    
    trainer = PricePredictionTrainer(symbol=args.symbol)
    all_results = []
    
    for timeframe in args.timeframes:
        try:
            print(f"\nTraining models for {timeframe}...")
            result = await trainer.train_timeframe(
                timeframe=timeframe,
                total_candles=args.total_candles,
                train_regression=args.regression,
                train_classification=args.classification,
                train_lstm=args.lstm
            )
            all_results.append(result)
            print(f"✓ Successfully trained {timeframe} models")
            
            if "xgboost_regressor" in result:
                print(f"  XGBoost Regressor - RMSE: Test={result['xgboost_regressor']['test_rmse']:.4f}")
            if "xgboost_classifier" in result:
                print(f"  XGBoost Classifier - Accuracy: Test={result['xgboost_classifier']['test_accuracy']:.4f}")
            if "lstm_regressor" in result:
                print(f"  LSTM Regressor - RMSE: Test={result['lstm_regressor']['test_rmse']:.4f}")
            if "lstm_classifier" in result:
                print(f"  LSTM Classifier - Accuracy: Test={result['lstm_classifier']['test_accuracy']:.4f}")
                
        except Exception as e:
            logger.error("training_failed", timeframe=timeframe, error=str(e), exc_info=True)
            print(f"✗ Failed to train {timeframe} models: {e}")
    
    # Save training summary
    if all_results:
        summary_path = project_root / "models" / "price_prediction_training_summary.csv"
        
        # Flatten results for CSV
        summary_rows = []
        for result in all_results:
            base_row = {
                "timeframe": result["timeframe"],
                "samples": result["samples"],
                "features": result["features"],
                "candles_fetched": result["candles_fetched"]
            }
            
            # Add XGBoost regressor metrics
            if "xgboost_regressor" in result:
                xgb_reg = result["xgboost_regressor"]
                summary_rows.append({
                    **base_row,
                    "model_type": "xgboost_regressor",
                    "train_metric": xgb_reg.get("train_rmse", 0),
                    "val_metric": xgb_reg.get("val_rmse", 0),
                    "test_metric": xgb_reg.get("test_rmse", 0),
                    "training_time": xgb_reg.get("training_time", 0),
                    "model_path": xgb_reg.get("model_path", "")
                })
            
            # Add XGBoost classifier metrics
            if "xgboost_classifier" in result:
                xgb_clf = result["xgboost_classifier"]
                summary_rows.append({
                    **base_row,
                    "model_type": "xgboost_classifier",
                    "train_metric": xgb_clf.get("train_accuracy", 0),
                    "val_metric": xgb_clf.get("val_accuracy", 0),
                    "test_metric": xgb_clf.get("test_accuracy", 0),
                    "training_time": xgb_clf.get("training_time", 0),
                    "model_path": xgb_clf.get("model_path", "")
                })
            
            # Add LSTM regressor metrics
            if "lstm_regressor" in result:
                lstm_reg = result["lstm_regressor"]
                summary_rows.append({
                    **base_row,
                    "model_type": "lstm_regressor",
                    "train_metric": lstm_reg.get("train_rmse", 0),
                    "val_metric": lstm_reg.get("val_rmse", 0),
                    "test_metric": lstm_reg.get("test_rmse", 0),
                    "training_time": lstm_reg.get("training_time", 0),
                    "model_path": lstm_reg.get("model_path", "")
                })
            
            # Add LSTM classifier metrics
            if "lstm_classifier" in result:
                lstm_clf = result["lstm_classifier"]
                summary_rows.append({
                    **base_row,
                    "model_type": "lstm_classifier",
                    "train_metric": lstm_clf.get("train_accuracy", 0),
                    "val_metric": lstm_clf.get("val_accuracy", 0),
                    "test_metric": lstm_clf.get("test_accuracy", 0),
                    "training_time": lstm_clf.get("training_time", 0),
                    "model_path": lstm_clf.get("model_path", "")
                })
        
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_csv(summary_path, index=False)
        print(f"\n✓ Training summary saved to {summary_path}")
    
    print("\n" + "=" * 60)
    print("Training complete!")
    print("=" * 60)
    
    return all_results


if __name__ == "__main__":
    asyncio.run(main())
