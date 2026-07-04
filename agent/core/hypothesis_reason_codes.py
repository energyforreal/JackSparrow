"""Shared hypothesis/thesis reason codes used across aggregator and policy."""

from __future__ import annotations

# Portfolio-mode flat hypothesis and legacy thesis engine flat states.
FLAT_HYPOTHESIS_CODES = frozenset({
    "hypothesis_no_rule_fired",
    "thesis_no_rule_fired",
})
