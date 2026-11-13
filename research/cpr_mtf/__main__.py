"""Build a local candlestick preview from the 5-minute BTCUSD parquet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from research.cpr_mtf.bars import load_btcusd_5m, resample_ohlcv
from research.cpr_mtf.contract import (
    PATTERN_CLASSES,
    SOURCE_RELATIVE,
    SPEC_VERSION,
    TIMEFRAMES,
    TRAIN_STRIDE,
)
from research.cpr_mtf.plots import save_preview
from research.cpr_mtf.splits import strided_ends
from research.cpr_mtf.windows import (
    bar_end,
    build_sample,
    eligible_ends,
    finite_window,
    last_complete_index,
    prepare_timeframe,
)


def main(argv: list[str] | None = None) -> int:
    """Load 5-minute candles, write previews, and return a process status.

    Args:
        argv: Optional argument list. ``None`` reads the process arguments.

    Returns:
        0 when the parquet was read, including a series too short to preview.
        1 when the parquet is missing.
    """
    parser = argparse.ArgumentParser(description="CPR-MTF causal preview")
    parser.add_argument("--source", default=SOURCE_RELATIVE, help="5-minute parquet path")
    parser.add_argument("--output", default="export/cpr_mtf", help="Preview and audit directory")
    parser.add_argument("--samples", type=int, default=3, help="Number of as-of charts")
    args = parser.parse_args(argv)
    source = Path(args.source)
    if not source.exists():
        print(f"BTCUSD 5-minute parquet was not found at {source}")
        return 1
    raw = load_btcusd_5m(source)
    audit = run_preview(raw, Path(args.output), samples=args.samples)
    print(
        f"{SPEC_VERSION} preview wrote {len(audit['samples'])} as-of samples "
        f"with data_quality={audit['data_quality']}"
    )
    return 0


def run_preview(raw: pd.DataFrame, output_dir: Path, samples: int = 3) -> dict[str, object]:
    """Resample, align, and draw the latest legal as-of clocks.

    Args:
        raw: Deduped 5-minute OHLCV.
        output_dir: Directory for ``preview/`` and ``audit.json``.
        samples: Maximum number of as-of clocks to draw, from the end.

    Returns:
        Audit document. ``data_quality`` is ``valid`` when at least one
        as-of clock has a finite 192-bar window on every timeframe.
    """
    prepared = {
        timeframe: prepare_timeframe(resample_ohlcv(raw, timeframe), timeframe)
        for timeframe in TIMEFRAMES
    }
    legal = _legal_clocks(prepared)
    chosen = legal[-samples:] if samples > 0 else []
    preview_dir = output_dir / "preview"
    sample_rows: list[dict[str, object]] = []
    for asof_end in chosen:
        sample = build_sample(prepared, asof_end)
        stamp = pd.Timestamp(asof_end).strftime("%Y%m%dT%H%M%SZ")
        for timeframe in TIMEFRAMES:
            end = int(sample["end_index"][timeframe])
            save_preview(
                prepared[timeframe].frame,
                prepared[timeframe].swings,
                sample["candidates"][timeframe],
                end,
                timeframe,
                preview_dir / f"{stamp}_{timeframe}.png",
            )
        sample_rows.append(_sample_audit(sample, prepared))
    audit = {
        "spec_version": SPEC_VERSION,
        "source_rows": int(len(raw)),
        "bars": {timeframe: int(len(prepared[timeframe].frame)) for timeframe in TIMEFRAMES},
        "samples": sample_rows,
        "data_quality": "valid" if sample_rows else "insufficient_history",
        "preview_dir": str(preview_dir),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit


def _legal_clocks(prepared: dict) -> list[pd.Timestamp]:
    """15-minute bar ends where every timeframe has a finite 192-bar window."""
    base = prepared["15m"]
    ends = strided_ends(eligible_ends(len(base.frame)), TRAIN_STRIDE)
    clocks: list[pd.Timestamp] = []
    for end in ends:
        asof_end = bar_end(pd.Timestamp(base.frame["time"].iloc[int(end)]), "15m")
        if _all_finite(prepared, asof_end):
            clocks.append(asof_end)
    return clocks


def _all_finite(prepared: dict, asof_end: pd.Timestamp) -> bool:
    """Return True when each timeframe can slice a finite 192-bar window."""
    for timeframe in TIMEFRAMES:
        series = prepared[timeframe]
        end = last_complete_index(series.frame, timeframe, asof_end)
        if end is None or not finite_window(series.matrix, end):
            return False
    return True


def _sample_audit(sample: dict, prepared: dict) -> dict[str, object]:
    """Counts for one as-of clock."""
    counts: dict[str, dict[str, int]] = {}
    swings: dict[str, int] = {}
    for timeframe in TIMEFRAMES:
        per_class = {name: 0 for name in PATTERN_CLASSES}
        for candidate in sample["candidates"][timeframe]:
            per_class[candidate.pattern] = per_class.get(candidate.pattern, 0) + 1
        counts[timeframe] = per_class
        end = int(sample["end_index"][timeframe])
        swings[timeframe] = sum(
            1 for swing in prepared[timeframe].swings if swing.confirmation_index <= end
        )
    windows = {
        timeframe: list(sample["windows"][timeframe].shape) for timeframe in TIMEFRAMES
    }
    return {
        "asof_end": pd.Timestamp(sample["asof_end"]).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "windows": windows,
        "swing_counts": swings,
        "candidate_counts": counts,
        "pair_count": len(sample["pairs"]),
    }


if __name__ == "__main__":
    sys.exit(main())
