"""Public Delta India history fetch for Colab transformer training."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from feature_store.transformer_btcusd.features import assemble_raw_frame

_RESOLUTION_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "1d": 1440,
}

# Documented candles cap is 2000; live India API has returned 4000 (newest-in-range
# when the window is larger). Request windows stay at the documented 2000. The loop
# walks backward from the oldest timestamp actually returned so a lower cap cannot
# open gaps. Production loaders use 500 for the same reason.
DELTA_CANDLE_PAGE_BARS = 2000
REQUEST_DELAY_SECONDS = 0.2
EMPTY_PAGE_RETRIES = 3
MIN_OHLCV_COMPLETENESS = 0.95


def _bar_seconds(resolution: str) -> int:
    if resolution not in _RESOLUTION_MINUTES:
        raise ValueError(
            f"Unsupported resolution {resolution!r}; "
            f"use one of {sorted(_RESOLUTION_MINUTES)}"
        )
    return int(_RESOLUTION_MINUTES[resolution]) * 60


def _parse_candle_rows(payload: Any) -> List[Dict[str, Any]]:
    """Normalize Delta history/candles payloads to a list of candle dicts."""
    if not isinstance(payload, dict):
        return []
    result = payload.get("result", [])
    if isinstance(result, dict):
        result = result.get("candles", []) or []
    if not isinstance(result, list):
        return []
    rows: List[Dict[str, Any]] = []
    for row in result:
        if isinstance(row, dict) and "time" in row:
            rows.append(row)
    return rows


def _candle_epoch(row: Dict[str, Any]) -> Optional[int]:
    try:
        return int(row["time"])
    except (KeyError, TypeError, ValueError):
        return None


def _request_candle_page(
    url: str,
    *,
    symbol: str,
    resolution: str,
    start_ts: int,
    end_ts: int,
) -> List[Dict[str, Any]]:
    last_error: Optional[Exception] = None
    for attempt in range(EMPTY_PAGE_RETRIES):
        try:
            response = requests.get(
                url,
                params={
                    "symbol": symbol,
                    "resolution": resolution,
                    "start": int(start_ts),
                    "end": int(end_ts),
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            time.sleep(REQUEST_DELAY_SECONDS * (attempt + 1))
            continue
        if payload.get("success") is False:
            last_error = RuntimeError(f"Delta candles error for {symbol}: {payload}")
            time.sleep(REQUEST_DELAY_SECONDS * (attempt + 1))
            continue
        rows = _parse_candle_rows(payload)
        if rows:
            return rows
        last_error = None
        time.sleep(REQUEST_DELAY_SECONDS * (attempt + 1))
    if last_error is not None:
        raise last_error
    return []


def _rows_to_frame(all_rows: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(all_rows)
    expected_cols = ["time", "open", "high", "low", "close", "volume"]
    df = df[[c for c in expected_cols if c in df.columns]]
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


def fetch_candles(
    symbol: str,
    resolution: str,
    start_ts: int,
    end_ts: int,
    base_url: str,
    *,
    page_bars: int = DELTA_CANDLE_PAGE_BARS,
) -> pd.DataFrame:
    """Pull OHLC-style candles with response-driven backward pagination.

    Each request covers at most ``page_bars`` of wall-clock. The next ``end`` is the
    oldest timestamp actually returned minus one second, so a server cap below the
    requested window cannot skip bars.

    Args:
        symbol: Delta symbol (e.g. ``BTCUSD``, ``FUNDING:BTCUSD``).
        resolution: Candle resolution key in ``_RESOLUTION_MINUTES``.
        start_ts: Inclusive Unix seconds.
        end_ts: Exclusive-ish Unix seconds (API treats the range as a window).
        base_url: Exchange origin, without a trailing path.
        page_bars: Max bars per request window (default documented 2000).

    Returns:
        Deduplicated OHLCV frame sorted by ``time`` ascending.

    Raises:
        ValueError: Unknown resolution.
        RuntimeError: No candles in the requested range.
    """
    url = f"{base_url.rstrip('/')}/v2/history/candles"
    bar_seconds = _bar_seconds(resolution)
    page_bars = max(1, int(page_bars))
    start_ts, end_ts = int(start_ts), int(end_ts)
    if end_ts <= start_ts:
        raise ValueError("end_ts must be greater than start_ts")

    all_rows: List[Dict[str, Any]] = []
    cursor_end = end_ts
    seen_oldest: Optional[int] = None
    max_pages = max(2, (end_ts - start_ts) // bar_seconds + 5)

    for _ in range(max_pages):
        if cursor_end <= start_ts:
            break
        page_start = max(start_ts, cursor_end - page_bars * bar_seconds)
        if page_start >= cursor_end:
            break
        rows = _request_candle_page(
            url,
            symbol=symbol,
            resolution=resolution,
            start_ts=page_start,
            end_ts=cursor_end,
        )
        if not rows:
            break
        epochs = [e for e in (_candle_epoch(r) for r in rows) if e is not None]
        if not epochs:
            break
        oldest = min(epochs)
        if seen_oldest is not None and oldest >= seen_oldest:
            break
        seen_oldest = oldest
        all_rows.extend(rows)
        cursor_end = oldest - 1
        time.sleep(REQUEST_DELAY_SECONDS)

    if not all_rows:
        raise RuntimeError(
            f"No candle data returned for symbol={symbol}; "
            "check symbol/resolution/date range."
        )
    return _rows_to_frame(all_rows)


def validate_ohlcv_completeness(
    df: pd.DataFrame,
    resolution: str,
    *,
    min_completeness: float = MIN_OHLCV_COMPLETENESS,
    symbol: str = "",
) -> Dict[str, Any]:
    """Measure gap rate on a native-TF OHLCV frame.

    Completeness is ``1 - gaps / (n - 1)`` where a gap is a bar-to-bar delta greater
    than ``1.5 * bar_seconds``. This catches sawtooth holes from truncated pages.

    Args:
        df: Frame with a ``time`` column (datetime or Unix seconds).
        resolution: Candle resolution key.
        min_completeness: Raise if the gap-free fraction is below this.
        symbol: Optional label for the error message.

    Returns:
        Report with ``rows``, ``gaps``, ``completeness``, and ``span_bars``.

    Raises:
        ValueError: Empty frame or completeness below ``min_completeness``.
    """
    if df is None or df.empty or "time" not in df.columns:
        raise ValueError("Cannot validate completeness on an empty OHLCV frame")
    bar_seconds = _bar_seconds(resolution)
    time_col = df["time"]
    if pd.api.types.is_datetime64_any_dtype(time_col):
        epochs = (pd.to_datetime(time_col, utc=True).astype("int64") // 10**9).tolist()
    else:
        epochs = pd.to_numeric(time_col, errors="coerce").dropna().astype(int).tolist()
    if len(epochs) < 2:
        raise ValueError("Need at least 2 OHLCV bars to validate completeness")

    gaps = 0
    for prev, cur in zip(epochs, epochs[1:]):
        if int(cur) - int(prev) > bar_seconds * 1.5:
            gaps += 1
    completeness = 1.0 - (gaps / max(1, len(epochs) - 1))
    span_bars = int((epochs[-1] - epochs[0]) // bar_seconds) + 1
    report: Dict[str, Any] = {
        "rows": len(epochs),
        "gaps": int(gaps),
        "completeness": round(float(completeness), 4),
        "span_bars": span_bars,
        "expected_bars": span_bars,
    }
    if completeness < min_completeness:
        label = f"{symbol} {resolution}".strip()
        raise ValueError(
            f"OHLCV completeness {completeness:.1%} below {min_completeness:.0%} "
            f"for {label or 'candles'} ({gaps} gaps, {len(epochs)} rows, "
            f"span {span_bars} bars). Refetch with response-driven pagination."
        )
    return report


def validate_derivatives_coverage(
    df: pd.DataFrame,
    *,
    min_coverage: float = 0.5,
    warn_coverage: float = 0.9,
) -> Dict[str, Any]:
    """Check funding/OI non-null coverage over the OHLCV timeline."""
    n = len(df)
    if n == 0:
        raise ValueError("Cannot validate derivatives coverage on empty frame")

    report: Dict[str, Any] = {"rows": n, "columns": {}}
    for col in ("funding_rate", "open_interest"):
        if col not in df.columns:
            report["columns"][col] = {"coverage": 0.0, "status": "missing"}
            continue
        coverage = float(df[col].notna().mean())
        status = "ok"
        if coverage < min_coverage:
            status = "error"
        elif coverage < warn_coverage:
            status = "warn"
        report["columns"][col] = {
            "coverage": round(coverage, 4),
            "status": status,
        }

    worst = min(v["coverage"] for v in report["columns"].values())
    report["worst_coverage"] = worst
    if worst < min_coverage:
        raise ValueError(
            "Derivatives coverage below minimum "
            f"({worst:.1%} < {min_coverage:.0%}): {report['columns']}"
        )
    return report


def fetch_history_bundle(
    *,
    symbol: str,
    resolution: str,
    history_days: int,
    base_url: str,
    min_derivatives_coverage: float = 0.5,
    derivatives_coverage_warn: float = 0.9,
    min_ohlcv_completeness: float = MIN_OHLCV_COMPLETENESS,
) -> pd.DataFrame:
    """Fetch OHLCV + funding + OI merged frame (notebook-compatible)."""
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=history_days)
    start_ts, end_ts = int(start_dt.timestamp()), int(end_dt.timestamp())

    raw_df = fetch_candles(symbol, resolution, start_ts, end_ts, base_url)
    ohlcv_report = validate_ohlcv_completeness(
        raw_df,
        resolution,
        min_completeness=min_ohlcv_completeness,
        symbol=symbol,
    )
    print(
        f"OHLCV {symbol} {resolution}: {ohlcv_report['rows']} bars, "
        f"completeness {ohlcv_report['completeness']:.1%}, "
        f"gaps={ohlcv_report['gaps']}"
    )

    try:
        funding_df = fetch_candles(
            f"FUNDING:{symbol}", resolution, start_ts, end_ts, base_url
        )
        funding_df = funding_df[["time", "close"]].rename(columns={"close": "funding_rate"})
    except Exception:
        funding_df = pd.DataFrame({"time": [], "funding_rate": []})

    try:
        oi_df = fetch_candles(f"OI:{symbol}", resolution, start_ts, end_ts, base_url)
        oi_df = oi_df[["time", "close"]].rename(columns={"close": "open_interest"})
    except Exception:
        oi_df = pd.DataFrame({"time": [], "open_interest": []})

    raw_df = assemble_raw_frame(raw_df, funding_df=funding_df, oi_df=oi_df)

    report = validate_derivatives_coverage(
        raw_df,
        min_coverage=min_derivatives_coverage,
        warn_coverage=derivatives_coverage_warn,
    )
    for col, info in report["columns"].items():
        if info["status"] == "warn":
            print(
                f"WARNING: {col} coverage {info['coverage']:.1%} "
                f"below recommended {derivatives_coverage_warn:.0%}"
            )
        elif info["status"] == "ok":
            print(f"{col} coverage: {info['coverage']:.1%}")

    return raw_df
