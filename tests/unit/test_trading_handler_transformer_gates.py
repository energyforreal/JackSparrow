"""Trading handler: transformer-native gates without legacy features.volatility."""

from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.config import settings
from agent.core.product_specs import ContractSpecs
import agent.events.handlers.trading_handler as trading_handler_mod
from agent.events.handlers.trading_handler import TradingEventHandler
from agent.events.schemas import DecisionReadyEvent


class _FakePositionManager:
    def get_position(self, symbol: str):
        return None


class _FakeExecutionModule:
    def __init__(self) -> None:
        self.position_manager = _FakePositionManager()

    async def get_exchange_portfolio_snapshot(self, symbol: str = "BTCUSD"):
        return None


@pytest.mark.asyncio
async def test_transformer_entry_without_volatility_feature(monkeypatch) -> None:
    monkeypatch.setattr(settings, "transformer_entry_gates", True)
    monkeypatch.setattr(settings, "legacy_feature_entry_gates", False)
    monkeypatch.setattr(settings, "ai_signal_minimal_entry_gates", False)
    monkeypatch.setattr(settings, "transformer_confidence_hold_floor", 0.40)
    monkeypatch.setattr(settings, "exchange_position_reconcile_enabled", False)
    monkeypatch.setattr(settings, "portfolio_fraction_lot_sizing", True)
    monkeypatch.setattr(settings, "entry_portfolio_margin_fraction", 0.60)
    monkeypatch.setattr(settings, "isolated_margin_leverage", 5)
    monkeypatch.setattr(settings, "sl_tp_mode", "path_pred")
    monkeypatch.setattr(settings, "initial_balance", 500000.0)
    monkeypatch.setattr(
        "agent.core.fx_rate.resolve_usdinr_rate",
        AsyncMock(return_value=83.0),
    )

    published: list = []

    async def capture_publish(event):
        published.append(event)

    monkeypatch.setattr(trading_handler_mod.event_bus, "publish", capture_publish)

    fake_state = SimpleNamespace(
        config={"market_data": {"price": 50000.0}},
        portfolio_value=500000.0,
        cash_balance=500000.0,
    )
    monkeypatch.setattr(
        trading_handler_mod,
        "context_manager",
        MagicMock(get_state=lambda: fake_state),
    )

    async def fake_specs(symbol: str) -> ContractSpecs:
        return ContractSpecs(
            symbol="BTCUSD",
            contract_value_btc=0.001,
            tick_size=0.5,
            product_id=27,
            taker_commission_rate=0.0005,
        )

    monkeypatch.setattr(trading_handler_mod, "get_contract_specs", fake_specs)

    risk = MagicMock()
    risk.portfolio = None
    risk.validate_trade = AsyncMock(return_value={"approved": True, "reason": "ok"})
    handler = TradingEventHandler(
        risk_manager=risk,
        delta_client=None,
        execution_module=_FakeExecutionModule(),
    )
    monkeypatch.setattr(
        handler.learning_system,
        "calibrate_runtime_confidence",
        lambda conf, **_k: float(conf),
    )

    now = datetime.now(timezone.utc)
    event = DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": "BUY",
            "confidence": 0.72,
            "position_size": 0.1,
            "timestamp": now,
            "server_timestamp_ms": int(now.timestamp() * 1000),
            "reasoning_chain": {
                "chain_id": "c1",
                "model_predictions": [],
                "market_context": {
                    "decision_path": "transformer_mtf",
                    # No features.volatility — must still approve under transformer gates
                    "execution_plan": {
                        "signal": "BUY",
                        "mfe": 0.02,
                        "mae": 0.01,
                        "stop_loss_pct": 0.01,
                        "take_profit_pct": 0.02,
                        "size_fraction": 0.5,
                        "size_scale": 1.0,
                        "rr_soft_action": "none",
                    },
                },
            },
        },
    )

    await handler.handle_decision_ready_for_trading(event)
    assert published, "expected RiskApprovedEvent without features.volatility"
    assert published[0].payload.get("ml_signal_source") == "transformer_mtf"
    assert published[0].payload.get("stop_loss") is not None
    assert published[0].payload.get("take_profit") is not None
