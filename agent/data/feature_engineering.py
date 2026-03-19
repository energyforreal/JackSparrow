"""
Feature engineering service.

Computes technical indicators and ML features from market data.
Delegates to UnifiedFeatureEngine for single source of truth (train-serve parity).
"""

from typing import Any, Dict, List

from feature_store.unified_feature_engine import UnifiedFeatureEngine


class FeatureEngineering:
    """Feature engineering service. Delegates to UnifiedFeatureEngine."""

    def __init__(self):
        """Initialize feature engineering."""
        self._engine = UnifiedFeatureEngine()

    async def compute_feature(
        self,
        feature_name: str,
        candles: List[Dict[str, Any]],
        resolution_minutes: int = 15,
    ) -> float:
        """Compute feature value from candles.

        Args:
            feature_name: Name of the feature to compute
            candles: List of candle dictionaries with market data
            resolution_minutes: Candle resolution in minutes (for returns_1h, returns_24h)

        Returns:
            Computed feature value as float

        Raises:
            ValueError: If input validation fails or feature cannot be computed
        """
        self._validate_input(feature_name, candles)
        return self._engine.compute_single(
            feature_name,
            candles,
            resolution_minutes=resolution_minutes,
        )

    def _validate_input(self, feature_name: str, candles: List[Dict[str, Any]]) -> None:
        """Validate input parameters."""
        if not feature_name or not isinstance(feature_name, str):
            raise ValueError("Feature name must be a non-empty string")

        if candles is None:
            raise ValueError("Candles cannot be None")

        if not candles:
            raise ValueError("No candles provided - at least one candle is required")

        if not all(isinstance(candle, dict) for candle in candles):
            raise ValueError("All candles must be dictionaries")

        import pandas as pd

        try:
            df = pd.DataFrame(candles)
        except Exception as e:
            raise ValueError(f"Failed to convert candles to DataFrame: {str(e)}")

        required_cols = ["close", "high", "low", "open", "volume"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {', '.join(missing_cols)}")

        numeric_cols = ["close", "high", "low", "open", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
                null_count = df[col].isnull().sum()
                if null_count > 0:
                    df[col] = df[col].ffill().bfill().fillna(0)
                    if null_count == len(df):
                        raise ValueError(
                            f"Column '{col}' contains only null/invalid values"
                        )

        import numpy as np

        for col in ["close", "high", "low", "open"]:
            if col in df.columns:
                if (df[col] <= 0).any():
                    raise ValueError(f"Column '{col}' contains non-positive values")
                if not np.isfinite(df[col]).all():
                    raise ValueError(
                        f"Column '{col}' contains non-finite values (NaN or Inf)"
                    )

        if "volume" in df.columns:
            if (df["volume"] < 0).any():
                raise ValueError("Column 'volume' contains negative values")
            if not np.isfinite(df["volume"]).all():
                raise ValueError(
                    "Column 'volume' contains non-finite values (NaN or Inf)"
                )

        if "high" in df.columns and "low" in df.columns:
            if (df["high"] < df["low"]).any():
                raise ValueError("Invalid data: high < low in some candles")

        if all(col in df.columns for col in ["high", "low", "close"]):
            if ((df["close"] > df["high"]) | (df["close"] < df["low"])).any():
                raise ValueError(
                    "Invalid data: close price outside high/low range in some candles"
                )

    def get_computation_method(self, feature_name: str) -> str:
        """Get computation method for feature."""
        methods = {
            "rsi_14": "Relative Strength Index (14-period)",
            "macd_signal": "MACD Signal Line (9-period EMA of MACD)",
            "bb_upper": "Bollinger Bands Upper (20-period SMA + 2*std)",
            "bb_lower": "Bollinger Bands Lower (20-period SMA - 2*std)",
            "volume_sma": "Volume Simple Moving Average (20-period)",
            "price_sma": "Price Simple Moving Average (20-period)",
            "volatility": "Volatility (std of returns, 20-period)",
        }
        return methods.get(feature_name, "Unknown")

    def validate_feature_order(self, feature_list: List[str]) -> Dict[str, Any]:
        """Validate that feature list matches expected order and count."""
        from feature_store.feature_registry import EXPECTED_FEATURE_COUNT

        validation_results = {
            "valid": True,
            "feature_count": len(feature_list),
            "expected_count": EXPECTED_FEATURE_COUNT,
            "missing_features": [],
            "errors": [],
        }

        if len(feature_list) != EXPECTED_FEATURE_COUNT:
            validation_results["valid"] = False
            validation_results["errors"].append(
                f"Feature count mismatch: got {len(feature_list)}, "
                f"expected {EXPECTED_FEATURE_COUNT}"
            )

        return validation_results
