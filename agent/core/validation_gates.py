"""
Validation gates for model promotion.

This module is intentionally lightweight and dependency-free so it can be
used both by local scripts and CI/unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union
import json


@dataclass(frozen=True)
class PaperTradeClose:
    timestamp: datetime
    position_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float  # realized pnl
    exit_reason: str


def _parse_iso_datetime(ts: str) -> datetime:
    # PaperTradeLogger uses IST (Asia/Kolkata) as the primary field (ISO 8601).
    return datetime.fromisoformat(ts)


def parse_paper_trade_close_lines(lines: Iterable[str]) -> List[PaperTradeClose]:
    """
    Parse CLOSE|... lines emitted by agent/core/paper_trade_logger.py.

    Expected format:
      CLOSE|{ts_ist}|{position_id}|{symbol}|{side}|{entry_price}|{exit_price}|{quantity}|{pnl}|{exit_reason}|utc_time=...
    """
    closes: List[PaperTradeClose] = []

    for raw in lines:
        line = raw.strip()
        if not line or not line.startswith("CLOSE|"):
            continue

        # Split into at most 10 fields; exit_reason is last.
        parts = line.split("|")
        if len(parts) < 10:
            # Malformed line; ignore (strict validation belongs in scripts/log monitors).
            continue

        _, ts, position_id, symbol, side, entry_price, exit_price, quantity, pnl, exit_reason = parts[:10]

        closes.append(
            PaperTradeClose(
                timestamp=_parse_iso_datetime(ts),
                position_id=position_id,
                symbol=symbol,
                side=side,
                entry_price=float(entry_price),
                exit_price=float(exit_price),
                quantity=float(quantity),
                pnl=float(pnl),
                exit_reason=exit_reason,
            )
        )

    return closes


def parse_paper_trade_log(log_path: Union[str, Path]) -> List[PaperTradeClose]:
    path = Path(log_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    with path.open("r", encoding="utf-8") as f:
        return parse_paper_trade_close_lines(f)


def compute_paper_soak_metrics(closes: Sequence[PaperTradeClose]) -> Dict[str, float]:
    """
    Compute activity + realized performance metrics from paper-trade closes.
    """
    if not closes:
        return {
            "total_trades": 0.0,
            "net_pnl": 0.0,
            "win_rate": 0.0,
            "trades_per_hour": 0.0,
            "max_drawdown_frac": 0.0,
        }

    sorted_closes = sorted(closes, key=lambda c: c.timestamp)
    total_trades = float(len(sorted_closes))
    net_pnl = float(sum(c.pnl for c in sorted_closes))

    wins = sum(1 for c in sorted_closes if c.pnl > 0)
    win_rate = wins / len(sorted_closes)

    t0 = sorted_closes[0].timestamp
    t1 = sorted_closes[-1].timestamp
    duration_hours = (t1 - t0).total_seconds() / 3600.0
    trades_per_hour = float(len(sorted_closes) / duration_hours) if duration_hours > 0 else total_trades

    # Cumulative PnL series (in close-time order)
    peak = 0.0
    cum = 0.0
    max_dd = 0.0
    for c in sorted_closes:
        cum += c.pnl
        peak = max(peak, cum)
        dd = peak - cum
        max_dd = max(max_dd, dd)

    # Normalize drawdown by absolute peak to keep scale stable across different horizons.
    denom = max(abs(peak), 1e-9)
    max_drawdown_frac = float(max_dd / denom)

    return {
        "total_trades": total_trades,
        "net_pnl": net_pnl,
        "win_rate": float(win_rate),
        "trades_per_hour": float(trades_per_hour),
        "max_drawdown_frac": float(max_drawdown_frac),
    }


def validate_paper_soak(
    metrics: Dict[str, float],
    *,
    min_total_trades: int = 10,
    min_trades_per_hour: float = 1.0,
    min_net_pnl: float = 0.0,
    max_drawdown_frac: float = 0.25,
) -> Tuple[bool, List[str]]:
    """
    Validate paper-soak performance metrics.

    Returns:
        (passed, reasons)
    """
    reasons: List[str] = []

    if metrics.get("total_trades", 0.0) < float(min_total_trades):
        reasons.append(f"total_trades < {min_total_trades}")
    if metrics.get("trades_per_hour", 0.0) < float(min_trades_per_hour):
        reasons.append(f"trades_per_hour < {min_trades_per_hour}")
    if metrics.get("net_pnl", 0.0) < float(min_net_pnl):
        reasons.append(f"net_pnl < {min_net_pnl}")
    if metrics.get("max_drawdown_frac", 0.0) > float(max_drawdown_frac):
        reasons.append(f"max_drawdown_frac > {max_drawdown_frac}")

    return (len(reasons) == 0, reasons)


def validate_walkforward_metadata(
    metadata: Dict[str, Any],
    *,
    min_sharpe: float = 0.0,
) -> Tuple[bool, List[str]]:
    """
    Validate walk-forward metrics from model metadata.
    """
    reasons: List[str] = []
    walkforward = metadata.get("walkforward_mean") or {}
    sharpe = walkforward.get("sharpe")
    if sharpe is None:
        reasons.append("walkforward_mean.sharpe missing")
        return False, reasons
    try:
        sharpe_f = float(sharpe)
    except (TypeError, ValueError):
        reasons.append("walkforward_mean.sharpe not numeric")
        return False, reasons

    if sharpe_f < float(min_sharpe):
        reasons.append(f"sharpe_proxy < {min_sharpe}")

    return (len(reasons) == 0, reasons)


def load_metadata_json(path: Union[str, Path]) -> Dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

