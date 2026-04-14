import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.core.validation_gates import (
    compute_paper_soak_metrics,
    parse_paper_trade_close_lines,
    validate_paper_soak,
    validate_walkforward_metadata,
)


def test_parse_and_compute_paper_soak_metrics():
    lines = [
        "CLOSE|2026-03-20T00:00:00+00:00|pos1|BTCUSD|BUY|100|110|1|10|take_profit",
        "CLOSE|2026-03-20T01:00:00+00:00|pos2|BTCUSD|SELL|110|100|1|10|take_profit",
        "CLOSE|2026-03-20T02:00:00+00:00|pos3|BTCUSD|BUY|100|95|1|-5|stop_loss",
        # Non-close lines should be ignored
        "TRADE|2026-03-20T05:30:00+05:30|trade1|BTCUSD|BUY|1|100|order_id=|position_id=pos1|reasoning_chain_id=|utc_time=2026-03-20T00:00:00+00:00|",
    ]

    closes = parse_paper_trade_close_lines(lines)
    assert len(closes) == 3

    metrics = compute_paper_soak_metrics(closes)
    assert metrics["total_trades"] == 3.0
    assert metrics["net_pnl"] == 15.0
    assert abs(metrics["win_rate"] - (2 / 3)) < 1e-9
    # 3 trades over 2 hours (00:00 -> 02:00)
    assert abs(metrics["trades_per_hour"] - 1.5) < 1e-9
    # Peak cumulative=20, trough=15 => drawdown=5 => 5/20 = 0.25
    assert abs(metrics["max_drawdown_frac"] - 0.25) < 1e-9

    passed, reasons = validate_paper_soak(
        metrics,
        min_total_trades=3,
        min_trades_per_hour=1.0,
        min_net_pnl=0.0,
        max_drawdown_frac=0.3,
    )
    assert passed, f"Expected pass, got reasons={reasons}"


def test_validate_walkforward_metadata():
    meta = {"walkforward_mean": {"sharpe": 0.2}}
    passed, _ = validate_walkforward_metadata(meta, min_sharpe=0.1)
    assert passed

    passed, reasons = validate_walkforward_metadata(meta, min_sharpe=0.5)
    assert not passed
    assert reasons

    passed, reasons = validate_walkforward_metadata({}, min_sharpe=0.1)
    assert not passed
    assert "walkforward_mean.sharpe missing" in reasons[0]

