"""Next-bar trade simulation with costs, funding, and one open position.

Entry is the next bar's open. The signal close is never an entry. Five-minute
bars decide whether a stop or a target printed first inside a higher-timeframe
bar. Without a finer bar, a dual touch exits at the stop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from research.swinging.contract import (
    BREAKEVEN_BAND,
    COLAB_DATA_ROOT,
    OUTCOME_COLUMNS,
    RESOLUTIONS,
    SLIPPAGE_BPS,
    STOP_ATR_MULT,
    SYMBOL,
    TAKER_FEE_RATE,
    TAKE_PROFIT_ATR_MULT,
    max_hold_bars,
)
from research.swinging.quality import normalize_ohlcv

_SLIP = SLIPPAGE_BPS / 10_000.0


def _lookup_index(frame: pd.DataFrame, timestamp: object, bar_index: int | None) -> int | None:
    if bar_index is not None and 0 <= int(bar_index) < len(frame):
        return int(bar_index)
    if "time" not in frame.columns or frame.empty or timestamp is None:
        return None
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    times = pd.to_datetime(frame["time"], utc=True)
    hits = list(times[times == stamp].index)
    if not hits:
        return None
    return int(hits[0])


def _atr(setup: dict[str, Any], frame: pd.DataFrame, index: int) -> float:
    raw = setup.get("atr_14")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0
    if value == value and value > 0.0:
        return value
    close = float(frame["close"].iloc[index])
    return max(abs(close) * 0.01, 1e-9)


def _brackets(direction: str, entry: float, atr: float) -> tuple[float, float]:
    risk = STOP_ATR_MULT * atr
    reward = TAKE_PROFIT_ATR_MULT * atr
    if direction == "long":
        return entry - risk, entry + reward
    return entry + risk, entry - reward


def _touch(direction: str, high: float, low: float, stop: float, take: float) -> tuple[str, float] | None:
    if direction == "long":
        hit_stop = low <= stop
        hit_take = high >= take
    else:
        hit_stop = high >= stop
        hit_take = low <= take
    if hit_stop and hit_take:
        return "stop_first", stop
    if hit_stop:
        return "stop", stop
    if hit_take:
        return "take_profit", take
    return None


def _funding_pnl(
    direction: str,
    entry_time: pd.Timestamp,
    exit_time: pd.Timestamp,
    funding: pd.DataFrame | None,
) -> tuple[float, bool]:
    if funding is None or funding.empty:
        return 0.0, True
    frame = funding.copy()
    if "time" not in frame.columns:
        return 0.0, True
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    rate_column = "funding_rate" if "funding_rate" in frame.columns else "close"
    window = frame[(frame["time"] > entry_time) & (frame["time"] <= exit_time)]
    if window.empty:
        return 0.0, False
    rates = pd.to_numeric(window[rate_column], errors="coerce").fillna(0.0)
    sign = 1.0 if direction == "long" else -1.0
    return float(-(sign * rates.sum())), False


def _returns(
    direction: str,
    entry_open: float,
    exit_raw: float,
    funding_pnl: float,
) -> dict[str, float]:
    if direction == "long":
        entry_fill = entry_open * (1.0 + _SLIP)
        exit_fill = exit_raw * (1.0 - _SLIP)
        gross = (exit_raw - entry_open) / entry_open
        traded = (exit_fill - entry_fill) / entry_fill
    else:
        entry_fill = entry_open * (1.0 - _SLIP)
        exit_fill = exit_raw * (1.0 + _SLIP)
        gross = (entry_open - exit_raw) / entry_open
        traded = (entry_fill - exit_fill) / entry_fill
    fee = 2.0 * TAKER_FEE_RATE
    net = traded - fee - funding_pnl
    return {
        "entry_price": float(entry_fill),
        "exit_price": float(exit_fill),
        "gross_return": float(gross),
        "fee_return": float(fee),
        "slippage_return": float(gross - traded),
        "net_return": float(net),
    }


def _label(reason: str, net_return: float) -> str:
    if reason == "expiry" and abs(net_return) <= BREAKEVEN_BAND:
        return "expiry"
    if abs(net_return) <= BREAKEVEN_BAND:
        return "breakeven"
    if net_return > 0.0:
        return "win"
    return "loss"


def _blank(setup: dict[str, Any], reason: str) -> dict[str, Any]:
    payload = {column: None for column in OUTCOME_COLUMNS}
    payload["exit_reason"] = reason
    payload["simulated"] = False
    payload["missing_funding"] = True
    payload["setup_id"] = setup.get("setup_id")
    return payload


def _path_bars(
    signal_frame: pd.DataFrame,
    entry_index: int,
    hold: int,
    lower: pd.DataFrame | None,
) -> pd.DataFrame:
    entry_time = pd.Timestamp(signal_frame["time"].iloc[entry_index])
    last_index = min(len(signal_frame) - 1, entry_index + hold - 1)
    if len(signal_frame) > 1:
        step = pd.Timestamp(signal_frame["time"].iloc[1]) - pd.Timestamp(signal_frame["time"].iloc[0])
    else:
        step = pd.Timedelta(minutes=5)
    end_time = pd.Timestamp(signal_frame["time"].iloc[last_index]) + step - pd.Timedelta(seconds=1)
    if lower is None or lower.empty:
        return signal_frame.iloc[entry_index : last_index + 1].reset_index(drop=True)
    bars = normalize_ohlcv(lower)
    bars = bars[(bars["time"] >= entry_time) & (bars["time"] <= end_time)]
    if bars.empty:
        return signal_frame.iloc[entry_index : last_index + 1].reset_index(drop=True)
    return bars.reset_index(drop=True)


def _excursions(direction: str, entry_open: float, path: pd.DataFrame) -> tuple[float, float]:
    if direction == "long":
        favorable = (path["high"].astype(float) - entry_open) / entry_open
        adverse = (entry_open - path["low"].astype(float)) / entry_open
    else:
        favorable = (entry_open - path["low"].astype(float)) / entry_open
        adverse = (path["high"].astype(float) - entry_open) / entry_open
    return float(favorable.max()), float(adverse.max())


def simulate_setup(
    setup: dict[str, Any],
    bars: pd.DataFrame,
    *,
    lower_bars: pd.DataFrame | None = None,
    funding: pd.DataFrame | None = None,
) -> dict[str, Any] | None:
    """Simulate one setup or drop it when the future is incomplete.

    Args:
        setup: Candidate row. ``direction`` of ``neutral`` is not simulated.
        bars: Signal-timeframe OHLCV.
        lower_bars: Optional 5-minute bars used to order stop and target.
        funding: Optional funding candles. A missing series sets
            ``missing_funding``.

    Returns:
        Outcome fields, or ``None`` when the hold cannot be resolved and
        neither stop nor target has printed.
    """
    direction = str(setup.get("direction") or "neutral")
    if direction not in ("long", "short"):
        return _blank(setup, "not_directional")
    frame = normalize_ohlcv(bars)
    raw_index = setup.get("bar_index")
    bar_index = int(raw_index) if raw_index is not None and str(raw_index) != "" else None
    signal_index = _lookup_index(frame, setup.get("signal_timestamp"), bar_index)
    if signal_index is None:
        return None
    entry_index = signal_index + 1
    hold = max_hold_bars(str(setup.get("timeframe") or setup.get("resolution") or "5m"))
    last_needed = entry_index + hold - 1
    if entry_index >= len(frame):
        return None
    entry_open = float(frame["open"].iloc[entry_index])
    if entry_open <= 0.0:
        return None
    atr = _atr(setup, frame, signal_index)
    stop, take = _brackets(direction, entry_open, atr)
    path = _path_bars(frame, entry_index, hold, lower_bars)
    if path.empty:
        return None
    exit_reason = None
    exit_raw = None
    exit_time = None
    for _, bar in path.iterrows():
        touch = _touch(direction, float(bar["high"]), float(bar["low"]), stop, take)
        if touch is not None:
            exit_reason, exit_raw = touch
            exit_time = pd.Timestamp(bar["time"])
            break
    resolved_early = exit_reason is not None
    if not resolved_early:
        if last_needed >= len(frame):
            return None
        exit_reason = "expiry"
        exit_raw = float(frame["close"].iloc[last_needed])
        exit_time = pd.Timestamp(frame["time"].iloc[last_needed])
    assert exit_raw is not None and exit_time is not None and exit_reason is not None
    entry_time = pd.Timestamp(frame["time"].iloc[entry_index])
    funding_pnl, missing_funding = _funding_pnl(direction, entry_time, exit_time, funding)
    priced = _returns(direction, entry_open, float(exit_raw), funding_pnl)
    visible = path.loc[pd.to_datetime(path["time"], utc=True) <= exit_time]
    if visible.empty:
        visible = path.iloc[:1]
    favorable, adverse = _excursions(direction, entry_open, visible)
    return {
        "setup_id": setup.get("setup_id"),
        "entry_timestamp": entry_time.isoformat(),
        "entry_price": priced["entry_price"],
        "stop_price": float(stop),
        "take_profit_price": float(take),
        "exit_timestamp": exit_time.isoformat(),
        "exit_price": priced["exit_price"],
        "exit_reason": exit_reason,
        "holding_seconds": float((exit_time - entry_time).total_seconds()),
        "mfe": favorable,
        "mae": adverse,
        "gross_return": priced["gross_return"],
        "fee_return": priced["fee_return"],
        "slippage_return": priced["slippage_return"],
        "funding_pnl": funding_pnl,
        "missing_funding": bool(missing_funding),
        "net_return": priced["net_return"],
        "outcome_label": _label(exit_reason, priced["net_return"]),
        "simulated": True,
    }


def simulate_portfolio(
    setups: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    lower_bars: pd.DataFrame | None = None,
    funding: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Simulate setups in time order and refuse a second open position.

    Args:
        setups: Candidate rows.
        bars: Signal-timeframe OHLCV.
        lower_bars: Optional finer bars.
        funding: Optional funding candles.

    Returns:
        Setup columns plus outcome columns. Overlaps stay in the frame with
        ``simulated`` false so they are not labeled as flat trades.
    """
    if setups.empty:
        return setups.copy()
    ordered = setups.copy()
    ordered["_signal_time"] = pd.to_datetime(ordered["signal_timestamp"], utc=True)
    ordered = ordered.sort_values(["_signal_time", "setup_id"]).reset_index(drop=True)
    busy_until: pd.Timestamp | None = None
    outcome_rows: list[dict[str, Any]] = []
    for record in ordered.to_dict(orient="records"):
        signal_time = pd.Timestamp(record["signal_timestamp"])
        if busy_until is not None and signal_time < busy_until:
            outcome_rows.append(_blank(record, "overlap_rejected"))
            continue
        outcome = simulate_setup(record, bars, lower_bars=lower_bars, funding=funding)
        if outcome is None:
            continue
        outcome_rows.append(outcome)
        if outcome.get("simulated") and outcome.get("exit_timestamp"):
            busy_until = pd.Timestamp(outcome["exit_timestamp"])
    if not outcome_rows:
        return ordered.drop(columns=["_signal_time"]).iloc[0:0]
    return _align_outcomes(ordered.drop(columns=["_signal_time"]), outcome_rows)


def _align_outcomes(setups: pd.DataFrame, outcome_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Attach outcomes that were produced in the same order as ``setups``.

    Unresolved setups are omitted from ``outcome_rows``, so this walks both
    sequences using setup id plus signal time and drops missing results.

    Args:
        setups: Sorted setup rows.
        outcome_rows: One result per setup that was not an unresolved tail.

    Returns:
        Joined frame.
    """
    if len(outcome_rows) == len(setups):
        extra = pd.DataFrame(outcome_rows).drop(columns=["setup_id"], errors="ignore")
        return pd.concat([setups.reset_index(drop=True), extra], axis=1)
    # Fallback when unresolved rows were skipped: match by id and timestamp order.
    remaining = outcome_rows.copy()
    kept_setups = []
    kept_outcomes = []
    for record in setups.to_dict(orient="records"):
        match = None
        for index, outcome in enumerate(remaining):
            if outcome.get("setup_id") == record.get("setup_id"):
                match = remaining.pop(index)
                break
        if match is None:
            continue
        kept_setups.append(record)
        kept_outcomes.append(match)
    if not kept_setups:
        return setups.iloc[0:0]
    extra = pd.DataFrame(kept_outcomes).drop(columns=["setup_id"], errors="ignore")
    return pd.concat([pd.DataFrame(kept_setups).reset_index(drop=True), extra], axis=1)


def materialize_outcomes(
    root: Path | str = COLAB_DATA_ROOT,
    *,
    symbol: str = SYMBOL,
    resolutions: tuple[str, ...] = RESOLUTIONS,
) -> dict[str, str]:
    """Simulate stored setups and write ``outcomes.parquet``.

    Args:
        root: Local dataset root.
        symbol: Instrument.
        resolutions: Resolutions that already have setups and OHLCV.

    Returns:
        Map of resolution to the outcome parquet path.
    """
    written: dict[str, str] = {}
    five_minute_path = Path(root) / symbol / "5m" / "ohlcv.parquet"
    five_minute = pd.read_parquet(five_minute_path) if five_minute_path.is_file() else None
    for resolution in resolutions:
        folder = Path(root) / symbol / resolution
        setup_path = folder / "setups.parquet"
        bar_path = folder / "ohlcv.parquet"
        if not setup_path.is_file() or not bar_path.is_file():
            continue
        funding_path = folder / "funding.parquet"
        funding = pd.read_parquet(funding_path) if funding_path.is_file() else None
        lower = None if resolution == "5m" else five_minute
        simulated = simulate_portfolio(
            pd.read_parquet(setup_path),
            pd.read_parquet(bar_path),
            lower_bars=lower,
            funding=funding,
        )
        destination = folder / "outcomes.parquet"
        simulated.to_parquet(destination, index=False)
        written[resolution] = str(destination)
    return written
