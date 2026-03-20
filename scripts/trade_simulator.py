#!/usr/bin/env python3
"""
Minimal trade-level backtest: OHLCV + optional signal column.

Exits use TP/SL as fractions of entry price (same spirit as live execution),
round-trip fee bps, and optional max bars in trade (time exit).

Example CSV columns: time,open,high,low,close  (optional: signal 1/-1/0)

  python scripts/trade_simulator.py --csv data/btc_5m.csv --side long \\
    --tp 0.003 --sl 0.002 --fee-bps 8 --max-bars 48
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Bar:
    idx: int
    high: float
    low: float
    close: float
    signal: int = 0


@dataclass
class Trade:
    side: str
    entry_idx: int
    entry_price: float
    exit_idx: int
    exit_price: float
    pnl_pct_gross: float
    pnl_pct_net: float
    reason: str


@dataclass
class SimResult:
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    max_drawdown_pct: float = 0.0
    final_equity: float = 1.0


def _read_bars(path: Path, signal_col: Optional[str]) -> List[Bar]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        rows = list(reader)

    def fnum(row: Dict[str, Any], *keys: str) -> float:
        for k in keys:
            if k in row and row[k] not in (None, ""):
                return float(row[k])
        raise KeyError(f"Missing numeric column; tried {keys}")

    bars: List[Bar] = []
    for i, row in enumerate(rows):
        h = fnum(row, "high", "High", "h")
        lo = fnum(row, "low", "Low", "l")
        c = fnum(row, "close", "Close", "c")
        sig = 0
        if signal_col and signal_col in row and row[signal_col] not in (None, ""):
            try:
                sig = int(float(row[signal_col]))
            except (TypeError, ValueError):
                sig = 0
        bars.append(Bar(idx=i, high=h, low=lo, close=c, signal=sig))
    return bars


def simulate_long_tp_sl(
    bars: List[Bar],
    tp: float,
    sl: float,
    fee_bps: float,
    max_bars: int,
    use_signal: bool,
) -> SimResult:
    """Long-only: enter on signal==1 at bar close; exit on intrabar TP/SL or time."""
    fee = fee_bps / 10000.0
    equity = 1.0
    peak = equity
    max_dd = 0.0
    curve: List[float] = [equity]
    trades: List[Trade] = []
    i = 0
    n = len(bars)

    while i < n:
        if use_signal and bars[i].signal != 1:
            i += 1
            curve.append(equity)
            continue

        entry_price = bars[i].close
        entry_idx = i
        tp_px = entry_price * (1.0 + tp)
        sl_px = entry_price * (1.0 - sl)
        exit_idx = entry_idx
        exit_price = entry_price
        reason = "open"

        end = min(n - 1, entry_idx + max_bars)
        for j in range(entry_idx + 1, end + 1):
            hi, lo = bars[j].high, bars[j].low
            # Conservative: if both hit same bar, assume SL first (worst case)
            if lo <= sl_px:
                exit_idx = j
                exit_price = sl_px
                reason = "SL"
                break
            if hi >= tp_px:
                exit_idx = j
                exit_price = tp_px
                reason = "TP"
                break
        else:
            exit_idx = end
            exit_price = bars[exit_idx].close
            reason = "time"

        pnl_gross = (exit_price - entry_price) / entry_price
        pnl_net = pnl_gross - 2 * fee
        equity *= 1.0 + pnl_net
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

        trades.append(
            Trade(
                side="long",
                entry_idx=entry_idx,
                entry_price=entry_price,
                exit_idx=exit_idx,
                exit_price=exit_price,
                pnl_pct_gross=pnl_gross * 100,
                pnl_pct_net=pnl_net * 100,
                reason=reason,
            )
        )
        curve.append(equity)
        i = exit_idx + 1

    return SimResult(
        trades=trades,
        equity_curve=curve,
        max_drawdown_pct=max_dd * 100,
        final_equity=equity,
    )


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="OHLCV TP/SL trade simulator (long)")
    p.add_argument("--csv", type=Path, required=True, help="CSV with OHLCV columns")
    p.add_argument("--tp", type=float, default=0.003, help="Take profit fraction (0.003 = 0.3%%)")
    p.add_argument("--sl", type=float, default=0.002, help="Stop loss fraction (0.002 = 0.2%%)")
    p.add_argument("--fee-bps", type=float, default=8.0, help="Round-trip fee in basis points (each leg)")
    p.add_argument("--max-bars", type=int, default=48, help="Max bars in trade (time exit)")
    p.add_argument(
        "--signal-col",
        type=str,
        default="",
        help="If set, only enter when this column == 1",
    )
    args = p.parse_args(argv)

    if not args.csv.is_file():
        print(f"File not found: {args.csv}", file=sys.stderr)
        return 2

    signal_col = args.signal_col.strip() or None
    bars = _read_bars(args.csv, signal_col)
    if not bars:
        print("No bars loaded", file=sys.stderr)
        return 2

    res = simulate_long_tp_sl(
        bars,
        tp=args.tp,
        sl=args.sl,
        fee_bps=args.fee_bps,
        max_bars=args.max_bars,
        use_signal=bool(signal_col),
    )

    wins = sum(1 for t in res.trades if t.pnl_pct_net > 0)
    losses = sum(1 for t in res.trades if t.pnl_pct_net <= 0)
    print(f"Trades: {len(res.trades)}  win/loss: {wins}/{losses}")
    print(f"Final equity (x): {res.final_equity:.6f}")
    print(f"Max drawdown: {res.max_drawdown_pct:.4f}%")
    if res.trades:
        rets = [t.pnl_pct_net for t in res.trades]
        mean_r = sum(rets) / len(rets)
        var = sum((r - mean_r) ** 2 for r in rets) / max(1, len(rets) - 1)
        sharpe_like = mean_r / math.sqrt(var) if var > 1e-12 else float("nan")
        print(f"Avg net return/trade %: {mean_r:.5f}  sharpe-like: {sharpe_like:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
