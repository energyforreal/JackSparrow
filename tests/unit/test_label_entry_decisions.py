"""Verify label_entry_decisions can resolve price from enriched reject snapshots."""

from __future__ import annotations

from tools.commands.label_entry_decisions import reference_price_from_metadata


def test_reference_price_from_current_price_fallback():
    meta = {
        "decision_context": {
            "current_price": 90123.5,
            "features": {},
        }
    }
    assert reference_price_from_metadata(meta) == 90123.5
