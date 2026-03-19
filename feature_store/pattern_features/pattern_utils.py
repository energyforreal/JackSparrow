"""Shared utilities for pattern feature computation."""

from dataclasses import dataclass

import pandas as pd


@dataclass
class CandleGeometry:
    """Pre-computed geometry for a single candle — avoids redundant calculations."""

    body: float
    upper_wick: float
    lower_wick: float
    total_range: float
    body_ratio: float
    upper_ratio: float
    lower_ratio: float
    is_bullish: bool

    @classmethod
    def from_row(cls, row: pd.Series) -> "CandleGeometry":
        body = abs(row["close"] - row["open"])
        upper_wick = row["high"] - max(row["open"], row["close"])
        lower_wick = min(row["open"], row["close"]) - row["low"]
        total_range = row["high"] - row["low"]
        safe_range = total_range if total_range > 1e-10 else 1e-10
        return cls(
            body=body,
            upper_wick=upper_wick,
            lower_wick=lower_wick,
            total_range=total_range,
            body_ratio=body / safe_range,
            upper_ratio=upper_wick / safe_range,
            lower_ratio=lower_wick / safe_range,
            is_bullish=row["close"] >= row["open"],
        )


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()
