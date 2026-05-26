"""
Synthetic market data builder for JackSparrow v43 scenario testing.

Each builder function returns a dict of DataFrames that can be injected
directly into the v43 model's context, bypassing the Delta exchange client.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, Any


def _base_candles(n: int, freq: str, base_price: float, seed: int = 42) -> pd.DataFrame:
    """Produce a basic OHLCV DataFrame with timestamp, open, high, low, close, volume."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    returns = rng.normal(0, 0.002, size=n)
    close = base_price * np.cumprod(1 + returns)
    spread = close * 0.001
    high = close + rng.uniform(0, spread, n)
    low = close - rng.uniform(0, spread, n)
    open_ = close - rng.normal(0, spread / 2, n)
    volume = rng.uniform(100, 600, n)
    df = pd.DataFrame({
        "timestamp": ts,
        "open": np.maximum(low, open_),
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    return df


def _funding_df(n: int, freq: str, rate: float = 0.0001, seed: int = 99) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    rates = rate + rng.normal(0, abs(rate) * 0.1, n)
    return pd.DataFrame({"timestamp": ts, "funding_rate": rates})


# ─────────────────────────────────────────────
# Scenario 1: Strong Breakout
# ─────────────────────────────────────────────

def build_strong_breakout(base_price: float = 45000.0) -> Dict[str, Any]:
    """
    Strong directional breakout: rising price, high volume expansion,
    ADX trending, clear upward momentum across timeframes.

    Expected agent behaviour: BUY / STRONG_BUY, high score, execution allowed.
    """
    rng = np.random.default_rng(1)
    n = 300
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")

    # Price accelerates upward — simulate breakout in last 50 bars
    trend = np.linspace(0, 0.08, n)                          # 8% trend
    noise = rng.normal(0, 0.001, n)
    returns = trend / n + noise
    close = base_price * np.cumprod(1 + returns)

    # Volume expansion on breakout
    volume = np.where(np.arange(n) > 230, rng.uniform(800, 1800, n), rng.uniform(100, 400, n))

    spread = close * 0.0008
    df5 = pd.DataFrame({
        "timestamp": ts,
        "open": close * (1 - rng.uniform(0, 0.001, n)),
        "high": close + spread,
        "low": close - spread * 0.5,
        "close": close,
        "volume": volume,
    })

    df15 = _base_candles(100, "15min", base_price, seed=11)
    df1h = _base_candles(50, "1h", base_price, seed=22)
    df_fund = _funding_df(50, "1h", rate=0.0001)
    df_oi = pd.DataFrame()   # optional
    df_mark = df5.copy()

    return {
        "scenario_name": "strong_breakout",
        "description": "Strong trending breakout with volume expansion",
        "feature_overrides": {
            "vol_regime": 1.25,
            "h_trend": 0.02,
            "di_spread": 8.0,
            "adx_14": 32.0,
            "rsi_14": 55.0,
        },
        "expected": {
            "thesis_direction": "LONG",
            "policy_signal_in": ["BUY", "STRONG_BUY"],
            "execute": True,
            "score_min": 70,
        },
        "frames": {
            "v43_df5m": df5,
            "v43_df15m": df15,
            "v43_df1h": df1h,
            "v43_df_funding": df_fund,
            "v43_df_oi": df_oi,
            "v43_df_mark": df_mark,
        },
    }


# ─────────────────────────────────────────────
# Scenario 2: Fake Breakout (volume trap)
# ─────────────────────────────────────────────

def build_fake_breakout(base_price: float = 45000.0) -> Dict[str, Any]:
    """
    Price pops briefly but volume is thin and mean-reverts — a bull trap.

    Expected: breakout detected, weak volume, ML uncertain → HOLD or reject.
    """
    rng = np.random.default_rng(2)
    n = 300
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")

    # Small pop then immediate reversal
    bump = np.concatenate([
        np.zeros(250),
        np.linspace(0, 0.02, 30),
        np.linspace(0.02, 0.0, 20),
    ])
    noise = rng.normal(0, 0.002, n)
    returns = bump / n + noise
    close = base_price * np.cumprod(1 + returns)

    # Thin volume on the "breakout"
    volume = rng.uniform(80, 200, n)

    spread = close * 0.001
    df5 = pd.DataFrame({
        "timestamp": ts,
        "open": close * (1 - rng.uniform(0, 0.001, n)),
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": volume,
    })

    df15 = _base_candles(100, "15min", base_price, seed=12)
    df1h = _base_candles(50, "1h", base_price, seed=23)
    df_fund = _funding_df(50, "1h", rate=0.0001)

    return {
        "scenario_name": "fake_breakout",
        "description": "Brief price pop with weak volume — bull trap",
        "expected": {
            "ml_uncertainty_high": True,
            "execute": False,
        },
        "frames": {
            "v43_df5m": df5,
            "v43_df15m": df15,
            "v43_df1h": df1h,
            "v43_df_funding": df_fund,
            "v43_df_oi": pd.DataFrame(),
            "v43_df_mark": df5.copy(),
        },
    }


# ─────────────────────────────────────────────
# Scenario 3: Chop / Sideways Market
# ─────────────────────────────────────────────

def build_chop_market(base_price: float = 45000.0) -> Dict[str, Any]:
    """
    Price oscillates in a tight range, low ATR, low ADX.

    Expected: HOLD, no execution, chop penalty in score.
    """
    rng = np.random.default_rng(3)
    n = 300
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")

    # Mean-reverting oscillation
    price = [base_price]
    for _ in range(n - 1):
        reversion = -0.1 * (price[-1] - base_price)
        price.append(price[-1] + reversion + rng.normal(0, 30))
    close = np.array(price)
    volume = rng.uniform(80, 200, n)
    spread = close * 0.0003

    df5 = pd.DataFrame({
        "timestamp": ts,
        "open": close - rng.uniform(0, 10, n),
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": volume,
    })

    df15 = _base_candles(100, "15min", base_price, seed=13)
    df1h = _base_candles(50, "1h", base_price, seed=24)
    df_fund = _funding_df(50, "1h", rate=0.0)

    return {
        "scenario_name": "chop_market",
        "description": "Sideways range-bound market with low volatility",
        "market_structure_overrides": {
            "chop_market": True,
            "market_type": "RANGING",
        },
        "expected": {
            "thesis_direction": "FLAT",
            "policy_signal_in": ["HOLD", "SELL"],
            "execute": False,
            "score_max": 85,
        },
        "frames": {
            "v43_df5m": df5,
            "v43_df15m": df15,
            "v43_df1h": df1h,
            "v43_df_funding": df_fund,
            "v43_df_oi": pd.DataFrame(),
            "v43_df_mark": df5.copy(),
        },
    }


# ─────────────────────────────────────────────
# Scenario 4: Liquidation Spike / Volatility Crush
# ─────────────────────────────────────────────

def build_liquidation_spike(base_price: float = 45000.0) -> Dict[str, Any]:
    """
    Sudden large price drop (−6%) followed by sharp recovery — liquidation cascade.

    Expected: volatility spike → reduced sizing → risk guards active.
    """
    rng = np.random.default_rng(4)
    n = 300
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")

    close = np.ones(n) * base_price
    # Sudden spike down at bar 200
    spike_start = 195
    close[spike_start:spike_start + 5] = base_price * np.array([0.99, 0.96, 0.94, 0.95, 0.97])
    close[spike_start + 5:] = base_price * 0.97 + rng.normal(0, 100, n - spike_start - 5)

    # Huge volume on the spike
    volume = rng.uniform(100, 300, n)
    volume[spike_start:spike_start + 5] = [5000, 12000, 8000, 6000, 4000]
    spread = np.abs(close) * 0.002

    df5 = pd.DataFrame({
        "timestamp": ts,
        "open": close - rng.normal(0, 50, n),
        "high": close + spread,
        "low": close - spread * 2,
        "close": close,
        "volume": volume,
    })
    df5["low"] = df5[["low", "open", "close"]].min(axis=1) - rng.uniform(10, 50, n)
    df5["high"] = df5[["high", "open", "close"]].max(axis=1)

    df15 = _base_candles(100, "15min", base_price, seed=14)
    df1h = _base_candles(50, "1h", base_price, seed=25)
    df_fund = _funding_df(50, "1h", rate=0.0008)  # elevated funding after spike

    return {
        "scenario_name": "liquidation_spike",
        "description": "Sudden -6% liquidation cascade with volume surge",
        "expected": {
            "execute": False,
            "reduced_sizing_or_hold": True,
        },
        "frames": {
            "v43_df5m": df5,
            "v43_df15m": df15,
            "v43_df1h": df1h,
            "v43_df_funding": df_fund,
            "v43_df_oi": pd.DataFrame(),
            "v43_df_mark": df5.copy(),
        },
    }


# ─────────────────────────────────────────────
# Scenario 5: High Drawdown State
# ─────────────────────────────────────────────

def build_high_drawdown(base_price: float = 45000.0) -> Dict[str, Any]:
    """
    Progressive trend downward — portfolio in drawdown.
    The portfolio_state passed in shows 15% drawdown.

    Expected: risk engine veto or reduced sizing, portfolio guard active.
    """
    rng = np.random.default_rng(5)
    n = 300
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")

    trend = np.linspace(0, -0.15, n)  # 15% decline
    noise = rng.normal(0, 0.001, n)
    returns = trend / n + noise
    close = base_price * np.cumprod(1 + returns)
    spread = close * 0.001

    df5 = pd.DataFrame({
        "timestamp": ts,
        "open": close * (1 + rng.uniform(-0.001, 0.001, n)),
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": rng.uniform(100, 400, n),
    })

    df15 = _base_candles(100, "15min", base_price * 0.9, seed=15)
    df1h = _base_candles(50, "1h", base_price * 0.85, seed=26)
    df_fund = _funding_df(50, "1h", rate=-0.0003)  # negative funding in downtrend

    # Portfolio state showing deep drawdown
    portfolio_state = {
        "portfolio_value": 8500.0,
        "cash_balance": 8500.0,
        "max_drawdown": 0.15,
        "sharpe_ratio": -1.2,
        "risk_limits": {"max_open_positions": 5},
        "positions": {},
    }

    return {
        "scenario_name": "high_drawdown",
        "description": "Portfolio at 15% drawdown — risk guard should limit/block trades",
        "expected": {
            "execute": False,
            "policy_signal_in": ["HOLD", "SELL", "BUY"],
        },
        "frames": {
            "v43_df5m": df5,
            "v43_df15m": df15,
            "v43_df1h": df1h,
            "v43_df_funding": df_fund,
            "v43_df_oi": pd.DataFrame(),
            "v43_df_mark": df5.copy(),
        },
        "portfolio_state": portfolio_state,
    }


# ─────────────────────────────────────────────
# Scenario 6: Thesis ↔ ML Disagreement
# ─────────────────────────────────────────────

def build_thesis_ml_disagreement(base_price: float = 45000.0) -> Dict[str, Any]:
    """
    Structure looks mildly bullish (thesis = BUY) but OHLCV features are
    ambiguous enough that ML expected_return hovers near threshold.

    Expected: policy fuses signals → HOLD (disagreement = no trade).
    """
    rng = np.random.default_rng(6)
    n = 300
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")

    # Slightly rising close but noisy — thesis sees breakout, ML is uncertain
    close = base_price + np.cumsum(rng.normal(2, 60, n))
    spread = np.abs(close) * 0.001

    df5 = pd.DataFrame({
        "timestamp": ts,
        "open": close - rng.normal(0, 20, n),
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": rng.uniform(80, 250, n),
    })

    df15 = _base_candles(100, "15min", base_price, seed=16)
    df1h = _base_candles(50, "1h", base_price, seed=27)
    df_fund = _funding_df(50, "1h", rate=0.0)

    return {
        "scenario_name": "thesis_ml_disagreement",
        "description": "Thesis sees BUY signal but ML expected_return is weak/borderline",
        "feature_overrides": {
            "vol_regime": 1.2,
            "h_trend": 0.015,
            "di_spread": 7.0,
            "adx_14": 28.0,
        },
        "expected": {
            "policy_signal_in": ["HOLD"],
            "execute": False,
            "thesis_direction": "LONG",
        },
        "frames": {
            "v43_df5m": df5,
            "v43_df15m": df15,
            "v43_df1h": df1h,
            "v43_df_funding": df_fund,
            "v43_df_oi": pd.DataFrame(),
            "v43_df_mark": df5.copy(),
        },
    }


# ─────────────────────────────────────────────
# Scenario 7: High ML Confidence But Bad Portfolio
# ─────────────────────────────────────────────

def build_high_confidence_bad_portfolio(base_price: float = 45000.0) -> Dict[str, Any]:
    """
    Strong trending price (ML should be confident) but portfolio is
    at maximum heat — already fully allocated.

    Expected: portfolio guard reduces or blocks the trade.
    """
    rng = np.random.default_rng(7)
    n = 300
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")

    trend = np.linspace(0, 0.12, n)
    noise = rng.normal(0, 0.0005, n)
    returns = trend / n + noise
    close = base_price * np.cumprod(1 + returns)
    spread = close * 0.0005
    volume = rng.uniform(500, 1500, n)

    df5 = pd.DataFrame({
        "timestamp": ts,
        "open": close * (1 - rng.uniform(0, 0.0005, n)),
        "high": close + spread,
        "low": close - spread * 0.3,
        "close": close,
        "volume": volume,
    })

    df15 = _base_candles(100, "15min", base_price, seed=17)
    df1h = _base_candles(50, "1h", base_price, seed=28)
    df_fund = _funding_df(50, "1h", rate=0.00015)

    # Portfolio fully allocated — 5/5 positions open
    portfolio_state = {
        "portfolio_value": 12000.0,
        "cash_balance": 500.0,   # only 4% cash left
        "max_drawdown": 0.02,
        "sharpe_ratio": 1.8,
        "risk_limits": {"max_open_positions": 5},
        "positions": {
            f"ASSET{i}": {"status": "open", "notional": 2000.0, "side": "LONG"}
            for i in range(5)
        },
    }

    return {
        "scenario_name": "high_confidence_bad_portfolio",
        "description": "Strong ML signal but portfolio at max heat (5/5 positions open)",
        "portfolio_position_side": "LONG",
        "feature_overrides": {
            "vol_regime": 1.15,
            "atr_pct": 0.0035,
            "h_trend": 0.02,
            "di_spread": 10.0,
            "adx_14": 35.0,
        },
        # Synthetic scalp ER is borderline vs gate5 min_edge_cost; boost for harness only
        "ml_expected_return_boost": 0.0004,
        "expected": {
            "portfolio_guard_action_in": ["reduce_size", "block"],
            "execute": False,
        },
        "frames": {
            "v43_df5m": df5,
            "v43_df15m": df15,
            "v43_df1h": df1h,
            "v43_df_funding": df_fund,
            "v43_df_oi": pd.DataFrame(),
            "v43_df_mark": df5.copy(),
        },
        "portfolio_state": portfolio_state,
    }


# ─────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────

ALL_SCENARIOS = [
    build_strong_breakout,
    build_fake_breakout,
    build_chop_market,
    build_liquidation_spike,
    build_high_drawdown,
    build_thesis_ml_disagreement,
    build_high_confidence_bad_portfolio,
]


def get_scenario(name: str) -> Dict[str, Any]:
    for fn in ALL_SCENARIOS:
        s = fn()
        if s["scenario_name"] == name:
            return s
    raise KeyError(f"Unknown scenario: {name}")


def list_scenario_names() -> list[str]:
    return [fn()["scenario_name"] for fn in ALL_SCENARIOS]
