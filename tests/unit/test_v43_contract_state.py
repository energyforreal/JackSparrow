"""Unit tests for v43 contract state parsing."""

from __future__ import annotations

import pytest

from agent.core.v43_contract_state import (
    ContractStateSnapshot,
    clear_contract_state_cache,
    enrich_contract_state_from_ticker,
    get_contract_state,
)


@pytest.mark.asyncio
async def test_get_contract_state_parses_product(monkeypatch) -> None:
    clear_contract_state_cache()

    async def _fake_fetch(symbol: str):
        return {
            "symbol": symbol,
            "state": "live",
            "trading_status": "operational",
            "maintenance_margin": "0.25",
            "initial_margin": "0.5",
            "max_leverage_notional": "100000",
            "impact_size": 10000,
            "price_band": "2.5",
            "product_specs": {"only_reduce_only_orders_allowed": False},
        }

    import agent.core.v43_contract_state as cs

    monkeypatch.setattr(cs, "_fetch_product_public", _fake_fetch)
    snap = await get_contract_state("BTCUSD")
    assert snap.is_operational
    assert snap.maintenance_margin == pytest.approx(0.25)


def test_enrich_contract_state_distances() -> None:
    base = ContractStateSnapshot(
        symbol="BTCUSD",
        state="live",
        trading_status="operational",
        only_reduce_only_orders_allowed=False,
        maintenance_margin=0.25,
        initial_margin=0.5,
        max_leverage_notional=100000.0,
        impact_size=10000.0,
        price_band_pct=2.5,
    )
    enriched = enrich_contract_state_from_ticker(
        base,
        {"mark_price": 100.0, "price_band_upper": 100.4, "price_band_lower": 99.6},
    )
    assert enriched.dist_to_upper_band_pct() == pytest.approx(0.4, rel=1e-3)
    assert enriched.dist_to_lower_band_pct() == pytest.approx(0.4, rel=1e-3)
