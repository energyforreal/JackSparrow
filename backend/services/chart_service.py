"""Assemble Market Analysis chart payloads from candles and cached decisions.

Does not re-run the scorer. Levels come from the last ``trading_decision``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

import structlog

from backend.core.redis import get_redis
from backend.services.market_service import market_service

logger = structlog.get_logger()

CHART_TIMEFRAMES = frozenset({"5m", "15m", "1h", "4h"})
_DIRECTIONAL = frozenset({"BUY", "SELL", "STRONG_BUY", "STRONG_SELL"})


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _unix_seconds(value: Any) -> Optional[int]:
    """Normalize candle timestamps to Unix seconds for Lightweight Charts."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 1e12:
            number /= 1000.0
        return int(number)
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
        if number > 1e12:
            number /= 1000.0
        return int(number)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _zone_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    zones: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        price = _as_float(item.get("price"))
        low = _as_float(item.get("low"))
        high = _as_float(item.get("high"))
        timeframe = str(item.get("timeframe") or "")
        if price is None or low is None or high is None or not timeframe:
            continue
        if price <= 0.0:
            continue
        zones.append(
            {
                "timeframe": timeframe,
                "price": price,
                "low": low,
                "high": high,
            }
        )
    return zones


def _risk_reward(
    entry: Optional[float],
    stop: Optional[float],
    take: Optional[float],
) -> Optional[float]:
    if entry is None or stop is None or take is None:
        return None
    risk = abs(entry - stop)
    if risk <= 0.0:
        return None
    return abs(take - entry) / risk


def _pattern_list(value: Any) -> List[Dict[str, Any]]:
    """Normalize active pattern markers from the cached trading decision."""
    if not isinstance(value, list):
        return []
    patterns: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        time_s = _unix_seconds(item.get("time"))
        name = str(item.get("name") or "").strip()
        if time_s is None or time_s <= 0 or not name:
            continue
        direction = str(item.get("direction") or "").lower()
        if direction not in {"bullish", "bearish"}:
            continue
        kind = str(item.get("kind") or "").lower()
        if kind not in {"candlestick", "chart"}:
            kind = "candlestick" if name.startswith("cdl_") else "chart"
        price = _as_float(item.get("price"))
        patterns.append(
            {
                "time": time_s,
                "name": name,
                "label": str(item.get("label") or name),
                "direction": direction,
                "timeframe": str(item.get("timeframe") or ""),
                "kind": kind,
                "price": price if price is not None and price > 0.0 else None,
            }
        )
    return patterns


def normalize_candles(
    raw_candles: Sequence[Mapping[str, Any]] | None,
) -> tuple[List[Dict[str, float]], List[Dict[str, float]]]:
    """Convert agent/market candles into chart candle and volume series."""
    candles: List[Dict[str, float]] = []
    volume: List[Dict[str, float]] = []
    if not raw_candles:
        return candles, volume
    for row in raw_candles:
        time_s = _unix_seconds(row.get("time", row.get("timestamp")))
        open_p = _as_float(row.get("open"))
        high_p = _as_float(row.get("high"))
        low_p = _as_float(row.get("low"))
        close_p = _as_float(row.get("close"))
        vol = _as_float(row.get("volume")) or 0.0
        if time_s is None or open_p is None or high_p is None or low_p is None or close_p is None:
            continue
        candles.append(
            {
                "time": float(time_s),
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
            }
        )
        volume.append({"time": float(time_s), "value": vol})
    candles.sort(key=lambda item: item["time"])
    volume.sort(key=lambda item: item["time"])
    return candles, volume


def trade_plan_from_decision(decision: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Map a cached ``trading_decision`` onto the chart trade_plan object."""
    empty = {
        "signal": "HOLD",
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "score": None,
        "risk_reward": None,
        "valid": False,
        "candle_timestamp": None,
        "decision_id": None,
    }
    if not isinstance(decision, Mapping):
        return empty
    signal = str(decision.get("signal") or "HOLD")
    risk = decision.get("risk") if isinstance(decision.get("risk"), Mapping) else {}
    entry = _as_float(decision.get("entry"))
    stop = _as_float(risk.get("stop_loss"))
    take = _as_float(risk.get("take_profit"))
    score = _as_float(decision.get("score"))
    invalidation = decision.get("invalidation")
    if isinstance(invalidation, list):
        invalid = [str(item) for item in invalidation if str(item)]
    else:
        text = str(invalidation or "")
        invalid = [] if not text else [text]
    directional = signal in _DIRECTIONAL
    valid_flag = decision.get("valid")
    if valid_flag is None:
        valid_flag = directional and not invalid
    else:
        valid_flag = bool(valid_flag)
    if not directional:
        entry = None
        stop = None
        take = None
    risk_reward = _as_float(decision.get("risk_reward"))
    if risk_reward is None:
        risk_reward = _risk_reward(entry, stop, take)
    return {
        "signal": signal,
        "entry": entry,
        "stop_loss": stop,
        "take_profit": take,
        "score": score,
        "risk_reward": risk_reward,
        "valid": bool(valid_flag),
        "candle_timestamp": decision.get("candle_timestamp"),
        "decision_id": decision.get("decision_id"),
    }


def levels_from_decision(
    decision: Mapping[str, Any] | None,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extract support/resistance zones from a trading decision."""
    if not isinstance(decision, Mapping):
        return [], []
    return (
        _zone_list(decision.get("support_zones")),
        _zone_list(decision.get("resistance_zones")),
    )


def patterns_from_decision(
    decision: Mapping[str, Any] | None,
) -> List[Dict[str, Any]]:
    """Extract in-house candlestick and chart-pattern hits."""
    if not isinstance(decision, Mapping):
        return []
    return _pattern_list(decision.get("active_patterns"))


def assemble_chart_payload(
    *,
    symbol: str,
    timeframe: str,
    market_data: Mapping[str, Any] | None,
    signal_snapshot: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    """Join OHLCV candles with the cached algorithmic decision."""
    raw_candles = None
    current_price = None
    if isinstance(market_data, Mapping):
        raw_candles = market_data.get("candles")
        current_price = _as_float(
            market_data.get("current_price", market_data.get("latest_price"))
        )
    candles, volume = normalize_candles(
        raw_candles if isinstance(raw_candles, list) else None
    )
    if current_price is None and candles:
        current_price = candles[-1]["close"]

    decision = None
    if isinstance(signal_snapshot, Mapping):
        nested = signal_snapshot.get("trading_decision")
        if isinstance(nested, Mapping):
            decision = nested
        elif signal_snapshot.get("decision_path"):
            decision = signal_snapshot

    support_zones, resistance_zones = levels_from_decision(decision)
    trade_plan = trade_plan_from_decision(decision)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": candles,
        "volume": volume,
        "current_price": current_price,
        "support_zones": support_zones,
        "resistance_zones": resistance_zones,
        "active_patterns": patterns_from_decision(decision),
        "trade_plan": trade_plan,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def load_last_signal(symbol: str) -> Optional[Dict[str, Any]]:
    """Read the Redis last-signal snapshot used by ``/signal/latest``."""
    try:
        redis = await get_redis(required=False)
        if not redis:
            return None
        raw = await redis.get(f"jacksparrow:last_signal:{symbol}")
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("chart_last_signal_load_failed", symbol=symbol, error=str(exc))
        return None


async def get_chart_data(
    *,
    symbol: str,
    timeframe: str,
    limit: int,
) -> Dict[str, Any]:
    """Fetch candles and merge with the cached decision for the chart UI."""
    if timeframe not in CHART_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    market_data = await market_service.get_market_data(
        symbol=symbol,
        interval=timeframe,
        limit=limit,
    )
    signal_snapshot = await load_last_signal(symbol)
    ticker = None
    try:
        ticker = await market_service.get_ticker(symbol)
    except Exception as exc:
        logger.warning("chart_ticker_load_failed", symbol=symbol, error=str(exc))
    merged_market: Dict[str, Any] = dict(market_data or {})
    if ticker and isinstance(ticker, dict):
        price = _as_float(ticker.get("price", ticker.get("close")))
        if price is not None:
            merged_market["current_price"] = price
    return assemble_chart_payload(
        symbol=symbol,
        timeframe=timeframe,
        market_data=merged_market,
        signal_snapshot=signal_snapshot,
    )
