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
        """Compute feature value from candles.
        
        Args:
            feature_name: Name of the feature to compute
            candles: List of candle dictionaries with market data
            
        Returns:
            Computed feature value as float
            
        Raises:
            ValueError: If input validation fails or feature cannot be computed
        """
        
        # Validate input parameters
        if not feature_name or not isinstance(feature_name, str):
            raise ValueError("Feature name must be a non-empty string")
        
        if candles is None:
            raise ValueError("Candles cannot be None")
        
        if not candles:
            raise ValueError("No candles provided - at least one candle is required")
        
        # Validate each candle is a dictionary
        if not all(isinstance(candle, dict) for candle in candles):
            raise ValueError("All candles must be dictionaries")
        
        # Convert to DataFrame
        try:
            df = pd.DataFrame(candles)
        except Exception as e:
            raise ValueError(f"Failed to convert candles to DataFrame: {str(e)}")
        
        # Ensure required columns exist
        required_cols = ["close", "high", "low", "open", "volume"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {', '.join(missing_cols)}")
        
        # Validate and clean numeric columns
        numeric_cols = ["close", "high", "low", "open", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                # Convert to numeric, coercing errors to NaN
                df[col] = pd.to_numeric(df[col], errors='coerce')
                # Check for null values
                null_count = df[col].isnull().sum()
                if null_count > 0:
                    # Fill null values with forward fill, then backward fill, then 0
                    df[col] = df[col].fillna(method='ffill').fillna(method='bfill').fillna(0)
                    if null_count == len(df):
                        raise ValueError(f"Column '{col}' contains only null/invalid values")
        
        # Validate numeric values are reasonable (not NaN, Inf, or negative for price/volume)
        for col in ["close", "high", "low", "open"]:
            if col in df.columns:
                if (df[col] <= 0).any():
                    raise ValueError(f"Column '{col}' contains non-positive values")
                if not np.isfinite(df[col]).all():
                    raise ValueError(f"Column '{col}' contains non-finite values (NaN or Inf)")
        
        # Volume can be zero but not negative
        if "volume" in df.columns:
            if (df["volume"] < 0).any():
                raise ValueError("Column 'volume' contains negative values")
            if not np.isfinite(df["volume"]).all():
                raise ValueError("Column 'volume' contains non-finite values (NaN or Inf)")
        
        # Validate high >= low and high >= close >= low
        if "high" in df.columns and "low" in df.columns:
            invalid_high_low = (df["high"] < df["low"]).any()
            if invalid_high_low:
                raise ValueError("Invalid data: high < low in some candles")
        
        if all(col in df.columns for col in ["high", "low", "close"]):
            invalid_close = ((df["close"] > df["high"]) | (df["close"] < df["low"])).any()
            if invalid_close:
                raise ValueError("Invalid data: close price outside high/low range in some candles")
        
        # Compute feature based on name
        try:
            # Price-based features
            if feature_name.startswith("sma_"):
                period = int(feature_name.split("_")[1])
                return self._compute_sma(df, period)
            elif feature_name.startswith("ema_"):
                period = int(feature_name.split("_")[1])
                return self._compute_ema_value(df, period)
            elif feature_name == "close_sma_20_ratio":
                return self._compute_close_sma_ratio(df, 20)
            elif feature_name == "close_sma_50_ratio":
                return self._compute_close_sma_ratio(df, 50)
            elif feature_name == "close_sma_200_ratio":
                return self._compute_close_sma_ratio(df, 200)
            elif feature_name == "high_low_spread":
                return self._compute_high_low_spread(df)
            elif feature_name == "close_open_ratio":
                return self._compute_close_open_ratio(df)
            elif feature_name == "body_size":
                return self._compute_body_size(df)
            elif feature_name == "upper_shadow":
                return self._compute_upper_shadow(df)
            elif feature_name == "lower_shadow":
                return self._compute_lower_shadow(df)
            
            # Momentum indicators
            elif feature_name == "rsi_14":
                return self._compute_rsi(df, period=14)
            elif feature_name == "rsi_7":
                return self._compute_rsi(df, period=7)
            elif feature_name == "stochastic_k_14":
                return self._compute_stochastic_k(df, period=14)
            elif feature_name == "stochastic_d_14":
                return self._compute_stochastic_d(df, period=14)
            elif feature_name == "williams_r_14":
                return self._compute_williams_r(df, period=14)
            elif feature_name == "cci_20":
                return self._compute_cci(df, period=20)
            elif feature_name == "roc_10":
                return self._compute_roc(df, period=10)
            elif feature_name == "roc_20":
                return self._compute_roc(df, period=20)
            elif feature_name == "momentum_10":
                return self._compute_momentum(df, period=10)
            elif feature_name == "momentum_20":
                return self._compute_momentum(df, period=20)
            
            # Trend indicators
            elif feature_name == "macd":
                return self._compute_macd(df)
            elif feature_name == "macd_signal":
                return self._compute_macd_signal(df)
            elif feature_name == "macd_histogram":
                return self._compute_macd_histogram(df)
            elif feature_name == "adx_14":
                return self._compute_adx(df, period=14)
            elif feature_name == "aroon_up":
                return self._compute_aroon_up(df, period=14)
            elif feature_name == "aroon_down":
                return self._compute_aroon_down(df, period=14)
            elif feature_name == "aroon_oscillator":
                return self._compute_aroon_oscillator(df, period=14)
            elif feature_name == "trend_strength":
                return self._compute_trend_strength(df)
            
            # Volatility indicators
            elif feature_name == "bb_upper":
                return self._compute_bollinger_upper(df, period=20)
            elif feature_name == "bb_lower":
                return self._compute_bollinger_lower(df, period=20)
            elif feature_name == "bb_width":
                return self._compute_bollinger_width(df, period=20)
            elif feature_name == "bb_position":
                return self._compute_bollinger_position(df, period=20)
            elif feature_name == "atr_14":
                return self._compute_atr(df, period=14)
            elif feature_name == "atr_20":
                return self._compute_atr(df, period=20)
            elif feature_name == "volatility_10":
                return self._compute_volatility(df, period=10)
            elif feature_name == "volatility_20":
                return self._compute_volatility(df, period=20)
            
            # Volume indicators
            elif feature_name == "volume_sma_20":
                return self._compute_volume_sma(df, period=20)
            elif feature_name == "volume_ratio":
                return self._compute_volume_ratio(df)
            elif feature_name == "obv":
                return self._compute_obv(df)
            elif feature_name == "volume_price_trend":
                return self._compute_volume_price_trend(df)
            elif feature_name == "accumulation_distribution":
                return self._compute_accumulation_distribution(df)
            elif feature_name == "chaikin_oscillator":
                return self._compute_chaikin_oscillator(df)
            
            # Returns
            elif feature_name == "returns_1h":
                return self._compute_returns(df, periods=4)  # Assuming 15m candles
            elif feature_name == "returns_24h":
                return self._compute_returns(df, periods=96)  # Assuming 15m candles
            elif feature_name == "log_returns":
                return self._compute_log_returns(df)
            elif feature_name == "price_change_pct":
                return self._compute_price_change_pct(df)
            elif feature_name == "volume_change_pct":
                return self._compute_volume_change_pct(df)
            elif feature_name == "high_low_ratio":
                return self._compute_high_low_ratio(df)
            
            # Legacy support
            elif feature_name == "volume_sma":
                return self._compute_volume_sma(df, period=20)
            elif feature_name == "price_sma":
                return self._compute_price_sma(df, period=20)
            elif feature_name == "volatility":
                return self._compute_volatility(df, period=20)
            else:
                raise ValueError(f"Unknown feature: {feature_name}")
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"Error computing feature '{feature_name}': {str(e)}")
    
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
    
    def _compute_sma(self, df: pd.DataFrame, period: int) -> float:
        """Compute Simple Moving Average."""
        close = df["close"].values
        if len(close) < period:
            return float(np.mean(close)) if len(close) > 0 else 0.0
        return float(np.mean(close[-period:]))
    
    def _compute_ema_value(self, df: pd.DataFrame, period: int) -> float:
        """Compute EMA value."""
        close = df["close"].values
        ema = self._ema(close, period)
        return float(ema[-1]) if len(ema) > 0 else float(close[-1]) if len(close) > 0 else 0.0
    
    def _compute_close_sma_ratio(self, df: pd.DataFrame, period: int) -> float:
        """Compute close price to SMA ratio."""
        close = df["close"].values[-1]
        sma = self._compute_sma(df, period)
        return float(close / sma) if sma > 0 else 1.0
    
    def _compute_high_low_spread(self, df: pd.DataFrame) -> float:
        """Compute high-low spread."""
        if len(df) == 0:
            return 0.0
        high = df["high"].values[-1]
        low = df["low"].values[-1]
        return float((high - low) / low) if low > 0 else 0.0
    
    def _compute_close_open_ratio(self, df: pd.DataFrame) -> float:
        """Compute close to open ratio."""
        if len(df) == 0:
            return 1.0
        close = df["close"].values[-1]
        open_price = df["open"].values[-1]
        return float(close / open_price) if open_price > 0 else 1.0
    
    def _compute_body_size(self, df: pd.DataFrame) -> float:
        """Compute candle body size."""
        if len(df) == 0:
            return 0.0
        close = df["close"].values[-1]
        open_price = df["open"].values[-1]
        return float(abs(close - open_price) / open_price) if open_price > 0 else 0.0
    
    def _compute_upper_shadow(self, df: pd.DataFrame) -> float:
        """Compute upper shadow size."""
        if len(df) == 0:
            return 0.0
        high = df["high"].values[-1]
        close = df["close"].values[-1]
        open_price = df["open"].values[-1]
        body_top = max(close, open_price)
        return float((high - body_top) / body_top) if body_top > 0 else 0.0
    
    def _compute_lower_shadow(self, df: pd.DataFrame) -> float:
        """Compute lower shadow size."""
        if len(df) == 0:
            return 0.0
        low = df["low"].values[-1]
        close = df["close"].values[-1]
        open_price = df["open"].values[-1]
        body_bottom = min(close, open_price)
        return float((body_bottom - low) / body_bottom) if body_bottom > 0 else 0.0
    
    def _compute_stochastic_k(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute Stochastic %K."""
        if len(df) < period:
            return 50.0
        high = df["high"].values[-period:]
        low = df["low"].values[-period:]
        close = df["close"].values[-1]
        highest_high = np.max(high)
        lowest_low = np.min(low)
        if highest_high == lowest_low:
            return 50.0
        return float(100 * (close - lowest_low) / (highest_high - lowest_low))
    
    def _compute_stochastic_d(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute Stochastic %D (3-period SMA of %K)."""
        if len(df) < period + 2:
            return 50.0
        k_values = []
        for i in range(3):
            # Fix: handle i == 0 case properly
            if i == 0:
                sliced_df = df
            else:
                sliced_df = df.iloc[:-i]
            
            # Ensure sliced dataframe has enough data
            if len(sliced_df) < period:
                k = 50.0
            else:
                k = self._compute_stochastic_k(sliced_df, period)
                # Ensure k is not None or invalid
                if k is None or not np.isfinite(k):
                    k = 50.0
            k_values.append(k)
        return float(np.mean(k_values))
    
    def _compute_williams_r(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute Williams %R."""
        if len(df) < period:
            return -50.0
        high = df["high"].values[-period:]
        low = df["low"].values[-period:]
        close = df["close"].values[-1]
        highest_high = np.max(high)
        lowest_low = np.min(low)
        if highest_high == lowest_low:
            return -50.0
        return float(-100 * (highest_high - close) / (highest_high - lowest_low))
    
    def _compute_cci(self, df: pd.DataFrame, period: int = 20) -> float:
        """Compute Commodity Channel Index."""
        if len(df) < period:
            return 0.0
        high = df["high"].values[-period:]
        low = df["low"].values[-period:]
        close = df["close"].values[-period:]
        typical_price = (high + low + close) / 3
        sma_tp = np.mean(typical_price)
        mean_deviation = np.mean(np.abs(typical_price - sma_tp))
        if mean_deviation == 0:
            return 0.0
        return float((typical_price[-1] - sma_tp) / (0.015 * mean_deviation))
    
    def _compute_roc(self, df: pd.DataFrame, period: int = 10) -> float:
        """Compute Rate of Change."""
        close = df["close"].values
        if len(close) < period + 1:
            return 0.0
        return float((close[-1] - close[-period-1]) / close[-period-1] * 100) if close[-period-1] > 0 else 0.0
    
    def _compute_momentum(self, df: pd.DataFrame, period: int = 10) -> float:
        """Compute Momentum."""
        close = df["close"].values
        if len(close) < period + 1:
            return 0.0
        return float(close[-1] - close[-period-1])
    
    def _compute_macd(self, df: pd.DataFrame) -> float:
        """Compute MACD line."""
        close = df["close"].values
        if len(close) < 26:
            return 0.0
        ema12 = self._ema(close, 12)
        ema26 = self._ema(close, 26)
        if len(ema12) == 0 or len(ema26) == 0:
            return 0.0
        macd = ema12 - ema26
        return float(macd[-1]) if len(macd) > 0 else 0.0
    
    def _compute_macd_histogram(self, df: pd.DataFrame) -> float:
        """Compute MACD histogram."""
        macd = self._compute_macd(df)
        signal = self._compute_macd_signal(df)
        return float(macd - signal)
    
    def _compute_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute Average Directional Index."""
        if len(df) < period + 1:
            return 0.0
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        
        # Calculate True Range and Directional Movement
        tr_list = []
        plus_dm = []
        minus_dm = []
        
        for i in range(1, len(df)):
            tr = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
            tr_list.append(tr)
            
            up_move = high[i] - high[i-1]
            down_move = low[i-1] - low[i]
            
            if up_move > down_move and up_move > 0:
                plus_dm.append(up_move)
            else:
                plus_dm.append(0)
            
            if down_move > up_move and down_move > 0:
                minus_dm.append(down_move)
            else:
                minus_dm.append(0)
        
        if len(tr_list) < period:
            return 0.0
        
        # Smooth TR and DM
        atr = np.mean(tr_list[-period:])
        plus_di = np.mean(plus_dm[-period:]) / atr * 100 if atr > 0 else 0
        minus_di = np.mean(minus_dm[-period:]) / atr * 100 if atr > 0 else 0
        
        # Calculate ADX
        dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
        return float(dx)
    
    def _compute_aroon_up(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute Aroon Up."""
        if len(df) < period:
            return 50.0
        high = df["high"].values[-period:]
        highest_idx = np.argmax(high)
        return float((period - highest_idx) / period * 100)
    
    def _compute_aroon_down(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute Aroon Down."""
        if len(df) < period:
            return 50.0
        low = df["low"].values[-period:]
        lowest_idx = np.argmin(low)
        return float((period - lowest_idx) / period * 100)
    
    def _compute_aroon_oscillator(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute Aroon Oscillator."""
        aroon_up = self._compute_aroon_up(df, period)
        aroon_down = self._compute_aroon_down(df, period)
        return float(aroon_up - aroon_down)
    
    def _compute_trend_strength(self, df: pd.DataFrame) -> float:
        """Compute trend strength (simplified)."""
        if len(df) < 20:
            return 0.0
        close = df["close"].values[-20:]
        sma_short = np.mean(close[-5:])
        sma_long = np.mean(close)
        return float((sma_short - sma_long) / sma_long * 100) if sma_long > 0 else 0.0
    
    def _compute_bollinger_width(self, df: pd.DataFrame, period: int = 20) -> float:
        """Compute Bollinger Bands width."""
        upper = self._compute_bollinger_upper(df, period)
        lower = self._compute_bollinger_lower(df, period)
        close = df["close"].values[-1]
        return float((upper - lower) / close * 100) if close > 0 else 0.0
    
    def _compute_bollinger_position(self, df: pd.DataFrame, period: int = 20) -> float:
        """Compute position within Bollinger Bands (0-1)."""
        upper = self._compute_bollinger_upper(df, period)
        lower = self._compute_bollinger_lower(df, period)
        close = df["close"].values[-1]
        if upper == lower:
            return 0.5
        return float((close - lower) / (upper - lower))
    
    def _compute_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Compute Average True Range."""
        if len(df) < period + 1:
            return 0.0
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        
        tr_list = []
        for i in range(1, len(df)):
            tr = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
            tr_list.append(tr)
        
        if len(tr_list) < period:
            return 0.0
        
        return float(np.mean(tr_list[-period:]))
    
    def _compute_volume_ratio(self, df: pd.DataFrame) -> float:
        """Compute volume ratio (current vs SMA)."""
        volume = df["volume"].values
        if len(volume) == 0:
            return 1.0
        current_volume = volume[-1]
        volume_sma = self._compute_volume_sma(df, 20)
        return float(current_volume / volume_sma) if volume_sma > 0 else 1.0
    
    def _compute_obv(self, df: pd.DataFrame) -> float:
        """Compute On-Balance Volume."""
        close = df["close"].values
        volume = df["volume"].values
        if len(close) < 2:
            return float(volume[0]) if len(volume) > 0 else 0.0
        
        obv = volume[0]
        for i in range(1, len(close)):
            if close[i] > close[i-1]:
                obv += volume[i]
            elif close[i] < close[i-1]:
                obv -= volume[i]
        
        return float(obv)
    
    def _compute_volume_price_trend(self, df: pd.DataFrame) -> float:
        """Compute Volume Price Trend."""
        close = df["close"].values
        volume = df["volume"].values
        if len(close) < 2:
            return 0.0
        
        vpt = 0.0
        for i in range(1, len(close)):
            if close[i-1] > 0:
                change_pct = (close[i] - close[i-1]) / close[i-1]
                vpt += volume[i] * change_pct
        
        return float(vpt)
    
    def _compute_accumulation_distribution(self, df: pd.DataFrame) -> float:
        """Compute Accumulation/Distribution Line."""
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        volume = df["volume"].values
        
        if len(close) == 0:
            return 0.0
        
        ad = 0.0
        for i in range(len(close)):
            if high[i] != low[i]:
                mfm = ((close[i] - low[i]) - (high[i] - close[i])) / (high[i] - low[i])
                ad += mfm * volume[i]
        
        return float(ad)
    
    def _compute_chaikin_oscillator(self, df: pd.DataFrame) -> float:
        """Compute Chaikin Oscillator."""
        if len(df) < 10:
            return 0.0
        ad = self._compute_accumulation_distribution(df)
        # Ensure ad is not None or invalid
        if ad is None or not np.isfinite(ad):
            ad = 0.0
        # Simplified: use recent AD values
        ad_values = []
        for i in range(min(10, len(df))):
            # Fix: handle i == 0 case properly
            if i == 0:
                sliced_df = df
            else:
                sliced_df = df.iloc[:-i]
            
            # Ensure sliced dataframe has data
            if len(sliced_df) == 0:
                ad_val = 0.0
            else:
                ad_val = self._compute_accumulation_distribution(sliced_df)
                # Ensure ad_val is not None or invalid
                if ad_val is None or not np.isfinite(ad_val):
                    ad_val = 0.0
            ad_values.append(ad_val)
        
        # Calculate EMAs with safety checks
        if len(ad_values) >= 3:
            ema_fast = np.mean(ad_values[-3:])
        else:
            ema_fast = ad if len(ad_values) == 0 else np.mean(ad_values)
        
        if len(ad_values) >= 10:
            ema_slow = np.mean(ad_values[-10:])
        else:
            ema_slow = ad if len(ad_values) == 0 else np.mean(ad_values)
        
        # Ensure both values are finite before subtraction
        if not np.isfinite(ema_fast):
            ema_fast = 0.0
        if not np.isfinite(ema_slow):
            ema_slow = 0.0
        
        result = ema_fast - ema_slow
        return float(result) if np.isfinite(result) else 0.0
    
    def _compute_returns(self, df: pd.DataFrame, periods: int = 1) -> float:
        """Compute returns over specified periods."""
        close = df["close"].values
        if len(close) < periods + 1:
            return 0.0
        return float((close[-1] - close[-periods-1]) / close[-periods-1] * 100) if close[-periods-1] > 0 else 0.0
    
    def _compute_log_returns(self, df: pd.DataFrame) -> float:
        """Compute log returns."""
        close = df["close"].values
        if len(close) < 2:
            return 0.0
        if close[-2] > 0:
            return float(np.log(close[-1] / close[-2]) * 100)
        return 0.0
    
    def _compute_price_change_pct(self, df: pd.DataFrame) -> float:
        """Compute price change percentage."""
        return self._compute_returns(df, periods=1)
    
    def _compute_volume_change_pct(self, df: pd.DataFrame) -> float:
        """Compute volume change percentage."""
        volume = df["volume"].values
        if len(volume) < 2:
            return 0.0
        if volume[-2] > 0:
            return float((volume[-1] - volume[-2]) / volume[-2] * 100)
        return 0.0
    
    def _compute_high_low_ratio(self, df: pd.DataFrame) -> float:
        """Compute high to low ratio."""
        if len(df) == 0:
            return 1.0
        high = df["high"].values[-1]
        low = df["low"].values[-1]
        return float(high / low) if low > 0 else 1.0
    
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
    
    def validate_feature_order(self, feature_list: List[str]) -> Dict[str, Any]:
        """Validate that feature list matches expected order and count.
        
        Args:
            feature_list: List of feature names to validate
            
        Returns:
            Dictionary with validation results
        """
        from agent.data.feature_list import EXPECTED_FEATURE_COUNT
        validation_results = {
            "valid": True,
            "feature_count": len(feature_list),
            "expected_count": EXPECTED_FEATURE_COUNT,
            "missing_features": [],
            "errors": []
        }
        
        if len(feature_list) != EXPECTED_FEATURE_COUNT:
            validation_results["valid"] = False
            validation_results["errors"].append(
                f"Feature count mismatch: got {len(feature_list)}, expected {EXPECTED_FEATURE_COUNT}"
            )
        
        # Check that all features can be computed (basic check)
        # This is a simplified check - full validation would require candles
        return validation_results

