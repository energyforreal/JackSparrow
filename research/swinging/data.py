"""Delta public-history collection onto a local directory.

Pagination, retries, and the 2,000-bar window live in
``scripts.colab.transformer_data.fetch_candles``. This module chooses the
symbol, walks the available span, and writes parquet plus a manifest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from research.swinging.contract import (
    BAR_SECONDS,
    COLAB_DATA_ROOT,
    DELTA_BASE_URL,
    HISTORY_START,
    PAGE_BARS,
    RESOLUTIONS,
    SERIES_KINDS,
    SYMBOL,
    series_symbol,
)
from research.swinging.quality import (
    build_manifest,
    drop_invalid_ohlc,
    normalize_ohlcv,
    quality_report,
    write_json,
)

FetchCandles = Callable[[str, str, int, int, str], pd.DataFrame]


def _default_fetch(
    symbol: str,
    resolution: str,
    start_ts: int,
    end_ts: int,
    base_url: str,
) -> pd.DataFrame:
    """Call the shared Colab candle fetcher.

    Args:
        symbol: Delta symbol, including ``MARK:`` / ``FUNDING:`` / ``OI:`` prefixes.
        resolution: Candle resolution.
        start_ts: Inclusive unix seconds.
        end_ts: Window end unix seconds.
        base_url: Exchange origin.

    Returns:
        Deduplicated OHLCV from ``fetch_candles``.
    """
    from scripts.colab.transformer_data import fetch_candles

    return fetch_candles(
        symbol,
        resolution,
        start_ts,
        end_ts,
        base_url,
        page_bars=PAGE_BARS,
    )


def _unix(value: datetime | pd.Timestamp) -> int:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return int(stamp.timestamp())


def fetch_series(
    kind: str,
    resolution: str,
    start: datetime,
    end: datetime,
    *,
    symbol: str = SYMBOL,
    base_url: str = DELTA_BASE_URL,
    fetcher: FetchCandles | None = None,
) -> tuple[pd.DataFrame, str | None]:
    """Fetch one series and keep an empty frame when the API has no rows.

    Args:
        kind: ``ohlcv``, ``mark``, ``funding``, or ``oi``.
        resolution: Candle resolution.
        start: Requested start. The returned frame may begin later.
        end: Requested end.
        symbol: Instrument.
        base_url: Exchange origin.
        fetcher: Replacement for ``fetch_candles``, used in tests.

    Returns:
        Normalized candles and an error string when the fetch failed.
    """
    fetch = fetcher or _default_fetch
    requested = series_symbol(kind, symbol)
    try:
        raw = fetch(requested, resolution, _unix(start), _unix(end), base_url)
    except (RuntimeError, ValueError) as exc:
        return normalize_ohlcv(pd.DataFrame()), str(exc)
    return normalize_ohlcv(raw), None


def _read_parquet(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return normalize_ohlcv(pd.DataFrame())
    return normalize_ohlcv(pd.read_parquet(path))


def _merge_incremental(existing: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    if existing.empty:
        return fresh
    if fresh.empty:
        return existing
    return normalize_ohlcv(pd.concat([existing, fresh], ignore_index=True))


def series_path(root: Path | str, resolution: str, kind: str, symbol: str = SYMBOL) -> Path:
    """Return the parquet path for one stored series.

    Args:
        root: Dataset root. On Colab this is ``/content/JackSparrow/data``.
        resolution: Candle resolution.
        kind: Series kind.
        symbol: Instrument.

    Returns:
        Parquet path.
    """
    return Path(root) / symbol / resolution / f"{kind}.parquet"


def collect_series(
    root: Path | str,
    resolution: str,
    kind: str,
    *,
    symbol: str = SYMBOL,
    base_url: str = DELTA_BASE_URL,
    fetcher: FetchCandles | None = None,
    incremental: bool = True,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Download one series into the local dataset root.

    Args:
        root: Directory that receives parquet and JSON reports.
        resolution: Candle resolution.
        kind: Series kind.
        symbol: Instrument.
        base_url: Exchange origin.
        fetcher: Optional fetch replacement.
        incremental: When true, request only bars after the stored maximum.
        start: Override the probe start. Defaults to ``HISTORY_START`` or the
            last stored bar.
        end: Override the probe end. Defaults to the current UTC time.

    Returns:
        The manifest written beside the parquet file.
    """
    destination = series_path(root, resolution, kind, symbol)
    existing = _read_parquet(destination) if incremental else normalize_ohlcv(pd.DataFrame())
    end_at = end or datetime.now(timezone.utc)
    if start is not None:
        start_at = start
    elif not existing.empty:
        start_at = pd.Timestamp(existing["time"].iloc[-1]).to_pydatetime()
        start_at = start_at + pd.Timedelta(seconds=BAR_SECONDS[resolution])
    else:
        start_at = pd.Timestamp(HISTORY_START).to_pydatetime()
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    frame, error = fetch_series(
        kind,
        resolution,
        start_at,
        end_at,
        symbol=symbol,
        base_url=base_url,
        fetcher=fetcher,
    )
    combined = _merge_incremental(existing, frame)
    if kind == "ohlcv":
        combined, invalid_rows = drop_invalid_ohlc(combined)
    else:
        invalid_rows = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(destination, index=False)
    manifest = build_manifest(
        combined,
        symbol=series_symbol(kind, symbol),
        resolution=resolution,
        kind=kind,
        source_error=error,
    )
    manifest["invalid_ohlc_rows"] = invalid_rows
    manifest["incremental"] = bool(incremental and not existing.empty)
    write_json(destination.with_name(f"{kind}_manifest.json"), manifest)
    return manifest


def collect_resolution(
    root: Path | str,
    resolution: str,
    *,
    symbol: str = SYMBOL,
    base_url: str = DELTA_BASE_URL,
    fetcher: FetchCandles | None = None,
    incremental: bool = True,
    five_minute: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Collect OHLCV, mark, funding, and open interest for one resolution.

    Args:
        root: Dataset root.
        resolution: Candle resolution.
        symbol: Instrument.
        base_url: Exchange origin.
        fetcher: Optional fetch replacement.
        incremental: Append to parquet already on disk.
        five_minute: Optional 5-minute frame for the resample check.

    Returns:
        Manifests and the OHLCV quality report.
    """
    manifests = {}
    for kind in SERIES_KINDS:
        manifests[kind] = collect_series(
            root,
            resolution,
            kind,
            symbol=symbol,
            base_url=base_url,
            fetcher=fetcher,
            incremental=incremental,
        )
    ohlcv = _read_parquet(series_path(root, resolution, "ohlcv", symbol))
    invalid = int(manifests["ohlcv"].get("invalid_ohlc_rows") or 0)
    reference = five_minute
    if reference is None and resolution != "5m":
        reference = _read_parquet(series_path(root, "5m", "ohlcv", symbol))
    report = quality_report(
        ohlcv,
        resolution,
        invalid_rows=invalid,
        five_minute=None if reference is None or reference.empty else reference,
    )
    write_json(series_path(root, resolution, "ohlcv", symbol).with_name("quality.json"), report)
    return {"manifests": manifests, "quality": report}


def collect_all(
    root: Path | str = COLAB_DATA_ROOT,
    *,
    symbol: str = SYMBOL,
    base_url: str = DELTA_BASE_URL,
    fetcher: FetchCandles | None = None,
    incremental: bool = True,
    resolutions: tuple[str, ...] = RESOLUTIONS,
) -> dict[str, Any]:
    """Collect every swinging resolution under ``root``.

    Args:
        root: Local dataset root. Colab uses ``/content/JackSparrow/data``.
        symbol: Instrument.
        base_url: Exchange origin.
        fetcher: Optional fetch replacement.
        incremental: Append to existing parquet.
        resolutions: Resolutions to request. Five-minute data is collected
            before higher timeframes so the resample check has a reference.

    Returns:
        One report per resolution.
    """
    ordered = tuple(dict.fromkeys(("5m", *resolutions)))
    reports: dict[str, Any] = {}
    for resolution in ordered:
        if resolution not in resolutions and resolution != "5m":
            continue
        reports[resolution] = collect_resolution(
            root,
            resolution,
            symbol=symbol,
            base_url=base_url,
            fetcher=fetcher,
            incremental=incremental,
        )
    return reports
