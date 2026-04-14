"""Unit tests for agent.core.paper_trade_entry ledger helpers."""

import pytest

from agent.core.paper_trade_entry import compute_paper_entry_ledger
from agent.core.config import settings
from unittest.mock import patch


def test_compute_paper_entry_ledger_split_mode():
    with patch.object(settings, "fee_accounting_mode", "split"):
        tv, fees_inr, ef = compute_paper_entry_ledger(
            quantity=2.0,
            fill_price=50000.0,
            contract_value_btc=0.001,
            usd_inr_rate=83.0,
            entry_fee_usd=None,
        )
    assert tv > 0
    assert ef > 0
    assert fees_inr == pytest.approx(ef * 83.0)


def test_compute_paper_entry_ledger_round_trip_mode():
    with patch.object(settings, "fee_accounting_mode", "round_trip"):
        tv, fees_inr, ef = compute_paper_entry_ledger(
            quantity=2.0,
            fill_price=50000.0,
            contract_value_btc=0.001,
            usd_inr_rate=83.0,
            entry_fee_usd=None,
        )
    assert tv > 0
    assert ef > 0
    assert fees_inr == 0.0
