from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.portfolio_service import PortfolioService


def _mock_closed_position() -> SimpleNamespace:
    return SimpleNamespace(
        position_id="pos_1",
        symbol="BTCUSD",
        side=SimpleNamespace(value="BUY"),
        quantity=Decimal("10"),
        entry_price=Decimal("50000"),
        current_price=Decimal("51000"),
        realized_pnl=Decimal("12.5"),
        opened_at=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc),
        closed_at=datetime(2026, 4, 14, 10, 15, 30, tzinfo=timezone.utc),
    )


def test_build_closed_trade_row_maps_all_required_fields():
    service = PortfolioService()
    row = service.build_closed_trade_row(_mock_closed_position(), Decimal("83"))

    assert row["trade_id"] == "closed_pos_1"
    assert row["position_id"] == "pos_1"
    assert row["symbol"] == "BTCUSD"
    assert row["entry_price"] == Decimal("50000")
    assert row["exit_price"] == Decimal("51000")
    assert row["pnl_usd"] == Decimal("12.5")
    assert row["pnl"] == Decimal("1037.5")
    assert row["duration_seconds"] == 930
    assert row["status"] == "CLOSED"
    assert row["executed_at"] == row["exit_time"]


@pytest.mark.asyncio
async def test_get_recent_closed_trades_returns_closed_rows(monkeypatch):
    service = PortfolioService()
    db = AsyncMock()
    db_result = Mock()
    db_result.scalars.return_value.all.return_value = [_mock_closed_position()]
    db.execute = AsyncMock(return_value=db_result)

    async def _mock_rate() -> float:
        return 80.0

    monkeypatch.setattr("backend.services.portfolio_service.get_usdinr_rate", _mock_rate)

    rows = await service.get_recent_closed_trades(db=db, symbol="BTCUSD", limit=10, offset=0)

    assert len(rows) == 1
    assert rows[0]["trade_id"] == "closed_pos_1"
    assert rows[0]["pnl"] == Decimal("1000.0")
