"""
Feature engineering service.

Computes technical indicators and ML features from market data.
"""

from typing import List, Dict, Any
import numpy as np
import pandas as pd


class FeatureEngineering:
    """Feature engineering service."""
    
    def __init__(self):
        """Initialize feature engineering."""
        pass
    
    async def compute_feature(self, feature_name: str, candles: List[Dict[str, Any]]) -> float:
        """Compute feature value from candles."""
        
        if not candles:
            raise ValueError("No candles provided")
        
        # Convert to DataFrame
        df = pd.DataFrame(candles)
        
        # Ensure required columns exist
        required_cols = ["close", "high", "low", "open", "volume"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Compute feature based on name
        if feature_name == "rsi_14":
            return self._compute_rsi(df, period=14)
        elif feature_name == "macd_signal":
            return self._compute_macd_signal(df)
        elif feature_name == "bb_upper":
            return self._compute_bollinger_upper(df, period=20)
        elif feature_name == "bb_lower":
            return self._compute_bollinger_lower(df, period=20)
        elif feature_name == "volume_sma":
            return self._compute_volume_sma(df, period=20)
        elif feature_name == "price_sma":
            return self._compute_price_sma(df, period=20)
        elif feature_name == "volatility":
            return self._compute_volatility(df, period=20)
        else:
            raise ValueError(f"Unknown feature: {feature_name}")
    
    def _compute_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute RSI indicator."""
        close = df["close"].values
        delta = np.diff(close)
        gains = np.where(delta > 0, delta, 0)
        losses = np.where(delta < 0, -delta, 0)
        
        avg_gain = np.mean(gains[-period:]) if len(gains) >= period else np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses[-period:]) if len(losses) >= period else np.mean(losses) if len(losses) > 0 else 0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)
    
    def _compute_macd_signal(self, df: pd.DataFrame) -> float:
        """Compute MACD signal line."""
        close = df["close"].values
        
        if len(close) < 26:
            return 0.0
        
        # Calculate EMA12 and EMA26
        ema12 = self._ema(close, 12)
        ema26 = self._ema(close, 26)
        
        # MACD line
        macd = ema12 - ema26
        
        # Signal line (9-period EMA of MACD)
        if len(macd) >= 9:
            signal = self._ema(macd, 9)
            return float(signal[-1]) if len(signal) > 0 else 0.0
        
        return 0.0
    
    def _compute_bollinger_upper(self, df: pd.DataFrame, period: int = 20, std_dev: int = 2) -> float:
        """Compute Bollinger Bands upper."""
        close = df["close"].values
        
        if len(close) < period:
            return float(close[-1]) if len(close) > 0 else 0.0
        
        sma = np.mean(close[-period:])
        std = np.std(close[-period:])
        
        return float(sma + (std_dev * std))
    
    def _compute_bollinger_lower(self, df: pd.DataFrame, period: int = 20, std_dev: int = 2) -> float:
        """Compute Bollinger Bands lower."""
        close = df["close"].values
        
        if len(close) < period:
            return float(close[-1]) if len(close) > 0 else 0.0
        
        sma = np.mean(close[-period:])
        std = np.std(close[-period:])
        
        return float(sma - (std_dev * std))
    
    def _compute_volume_sma(self, df: pd.DataFrame, period: int = 20) -> float:
        """Compute volume SMA."""
        volume = df["volume"].values
        
        if len(volume) < period:
            return float(np.mean(volume)) if len(volume) > 0 else 0.0
        
        return float(np.mean(volume[-period:]))
    
    def _compute_price_sma(self, df: pd.DataFrame, period: int = 20) -> float:
        """Compute price SMA."""
        close = df["close"].values
        
        if len(close) < period:
            return float(np.mean(close)) if len(close) > 0 else 0.0
        
        return float(np.mean(close[-period:]))
    
    def _compute_volatility(self, df: pd.DataFrame, period: int = 20) -> float:
        """Compute volatility (standard deviation of returns)."""
        close = df["close"].values
        
        if len(close) < period:
            return 0.0
        
        returns = np.diff(close[-period:]) / close[-period:-1]
        volatility = np.std(returns)
        
        return float(volatility * 100)  # Return as percentage
    
    def _ema(self, values: np.ndarray, period: int) -> np.ndarray:
        """Compute Exponential Moving Average."""
        if len(values) < period:
            return np.array([])
        
        ema = np.zeros_like(values)
        ema[0] = values[0]
        
        multiplier = 2 / (period + 1)
        
        for i in range(1, len(values)):
            ema[i] = (values[i] - ema[i-1]) * multiplier + ema[i-1]
        
        return ema
    
    def get_computation_method(self, feature_name: str) -> str:
        """Get computation method for feature."""
        methods = {
            "rsi_14": "Relative Strength Index (14-period)",
            "macd_signal": "MACD Signal Line (9-period EMA of MACD)",
            "bb_upper": "Bollinger Bands Upper (20-period SMA + 2*std)",
            "bb_lower": "Bollinger Bands Lower (20-period SMA - 2*std)",
            "volume_sma": "Volume Simple Moving Average (20-period)",
            "price_sma": "Price Simple Moving Average (20-period)",
            "volatility": "Volatility (std of returns, 20-period)"
        }
        return methods.get(feature_name, "Unknown")

