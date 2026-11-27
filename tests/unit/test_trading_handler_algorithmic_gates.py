"""Trading handler: algorithmic entries skip ML gates and keep risk controls."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.core.config import settings
from agent.core.product_specs import ContractSpecs
import agent.events.handlers.trading_handler as trading_handler_mod
from agent.events.handlers.trading_handler import TradingEventHandler
from agent.events.schemas import DecisionReadyEvent


class _FakePositionManager:
    def __init__(self, position=None) -> None:
        self._position = position

    def get_position(self, symbol: str):
        return self._position


class _FakeExecutionModule:
    def __init__(self, position=None) -> None:
        self.position_manager = _FakePositionManager(position)

    async def get_exchange_portfolio_snapshot(self, symbol: str = "BTCUSD"):
        return None


def _algo_event(
    *,
    signal: str = "BUY",
    confidence: float = 0.72,
    score: float = 72.0,
    stop_loss: float | None = 49000.0,
    take_profit: float | None = 52000.0,
    features: dict | None = None,
) -> DecisionReadyEvent:
    now = datetime.now(timezone.utc)
    plan: dict = {"atr_14": 100.0}
    if stop_loss is not None:
        plan["stop_loss"] = stop_loss
    if take_profit is not None:
        plan["take_profit"] = take_profit
    return DecisionReadyEvent(
        source="test",
        payload={
            "symbol": "BTCUSD",
            "signal": signal,
            "confidence": confidence,
            "position_size": 0.0,
            "timestamp": now,
            "server_timestamp_ms": int(now.timestamp() * 1000),
            "trading_decision": {"decision_id": "algo-1", "score": score},
            "reasoning_chain": {
                "chain_id": "algo-chain",
                "model_predictions": [],
                "market_context": {
                    "decision_path": "algorithmic",
                    "decision_id": "algo-1",
                    "algo_score": score,
                    "algo_signal_validated": signal != "HOLD",
                    "invalidation": "",
                    "features": features if features is not None else {"atr_14": 100.0},
                    "execution_plan": plan,
                },
            },
        },
    )


def _install_handler(monkeypatch, *, position=None) -> tuple[TradingEventHandler, list, list]:
    monkeypatch.setattr(settings, "entry_gates_enabled", True)
    monkeypatch.setattr(settings, "transformer_entry_gates", True)
    monkeypatch.setattr(settings, "legacy_feature_entry_gates", False)
    monkeypatch.setattr(settings, "ai_signal_minimal_entry_gates", False)
    monkeypatch.setattr(settings, "transformer_confidence_hold_floor", 0.80)
    monkeypatch.setattr(settings, "transformer_min_confidence", 0.80)
    monkeypatch.setattr(settings, "min_confidence_threshold", 0.80)
    monkeypatch.setattr(settings, "ai_signal_min_entry_confidence", 0.80)
    monkeypatch.setattr(settings, "exchange_position_reconcile_enabled", False)
    monkeypatch.setattr(settings, "portfolio_fraction_lot_sizing", True)
    monkeypatch.setattr(settings, "entry_portfolio_margin_fraction", 0.60)
    monkeypatch.setattr(settings, "isolated_margin_leverage", 5)
    monkeypatch.setattr(settings, "sl_tp_mode", "atr")
    monkeypatch.setattr(settings, "use_atr_scaled_sl_tp", True)
    monkeypatch.setattr(settings, "initial_balance", 500000.0)
    monkeypatch.setattr(settings, "trade_signal_debounce_seconds", 0)
    monkeypatch.setattr(settings, "max_trades_per_hour", 0)
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
        execution_module=_FakeExecutionModule(position),
    )
    reasons: list[str] = []

    def capture_reject(reason: str, **kwargs):
        reasons.append(reason)

    monkeypatch.setattr(handler, "_log_entry_rejected", capture_reject)
    return handler, published, reasons


@pytest.mark.asyncio
async def test_algorithmic_score_72_bypasses_ml_confidence_floor(monkeypatch) -> None:
    handler, published, reasons = _install_handler(monkeypatch)
    await handler.handle_decision_ready_for_trading(_algo_event())
    assert published, "qualified algorithmic entry should reach risk approval"
    assert "low_confidence_reject" not in reasons
    assert "low_ai_signal_confidence" not in reasons
    assert published[0].payload.get("algo_signal_validated") is True
    assert published[0].payload.get("ml_signal_validated") is False
    assert published[0].payload.get("sl_tp_source") == "algorithmic"
    assert published[0].payload.get("stop_loss") == 49000.0
    assert published[0].payload.get("take_profit") == 52000.0
    handler.risk_manager.validate_trade.assert_awaited()


@pytest.mark.asyncio
async def test_transformer_path_still_hits_confidence_floor(monkeypatch) -> None:
    handler, published, reasons = _install_handler(monkeypatch)
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
                "chain_id": "ml-1",
                "model_predictions": [],
                "market_context": {"decision_path": "transformer_agent_synthesis"},
            },
        },
    )
    await handler.handle_decision_ready_for_trading(event)
    assert not published
    assert reasons == ["low_ai_signal_confidence"]
    handler.risk_manager.validate_trade.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_position_still_blocks_algorithmic_entry(monkeypatch) -> None:
    handler, published, reasons = _install_handler(
        monkeypatch,
        position={"status": "open", "side": "long"},
    )
    await handler.handle_decision_ready_for_trading(_algo_event())
    assert not published
    assert reasons == ["open_position_blocks_entry"]


@pytest.mark.asyncio
async def test_missing_brackets_do_not_fall_back_to_atr(monkeypatch) -> None:
    handler, published, reasons = _install_handler(monkeypatch)
    await handler.handle_decision_ready_for_trading(
        _algo_event(stop_loss=None, take_profit=None, features={"atr_14": 250.0})
    )
    assert not published
    assert reasons == ["algorithmic_invalid_brackets"]


@pytest.mark.asyncio
async def test_legacy_feature_gates_do_not_require_volatility(monkeypatch) -> None:
    handler, published, reasons = _install_handler(monkeypatch)
    monkeypatch.setattr(settings, "legacy_feature_entry_gates", True)
    await handler.handle_decision_ready_for_trading(
        _algo_event(features={"atr_14": 100.0})
    )
    assert published
    assert "missing_volatility_reject" not in reasons
    assert published[0].payload.get("sl_tp_source") == "algorithmic"
