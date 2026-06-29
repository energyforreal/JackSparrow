"""Structural Gate Engine — categorical trade permission checks."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from agent.core.config import settings
from agent.core.strategy_types import MarketStructureSnapshot
from agent.core.v43_signal_gates import (
    V43GateState,
    apply_post_threshold_gates,
    apply_post_threshold_gates_short,
)
from agent.intelligence.market_types import MarketStateSnapshot, NarrativeEvent, StructuralGateResult

logger = structlog.get_logger()

_CATEGORIES = ("trend", "structure", "breakout", "liquidity", "volatility", "risk")


def _check_trend(snapshot: MarketStateSnapshot) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    if snapshot.trend == "neutral":
        reasons.append("structural_trend_neutral")
        return False, reasons
    min_age = int(getattr(settings, "structural_gate_min_trend_age", 3) or 3)
    if snapshot.trend_age_candles < min_age:
        reasons.append(f"structural_trend_too_young={snapshot.trend_age_candles}")
        return False, reasons
    if snapshot.trend_strength == "weak":
        reasons.append("structural_trend_weak")
        return False, reasons
    h1_role = snapshot.mtf.get("h1", "")
    if "counter" in h1_role:
        reasons.append("structural_mtf_h1_counter")
        return False, reasons
    return True, reasons


def _check_structure(
    snapshot: MarketStateSnapshot,
    structure: Optional[MarketStructureSnapshot],
) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    if structure is None:
        return True, reasons
    if structure.market_type in ("CRISIS", "LOW_VOL"):
        reasons.append(f"structural_market_type_{structure.market_type}")
        return False, reasons
    if snapshot.structure in ("CRISIS", "LOW_VOL"):
        reasons.append(f"structural_snapshot_{snapshot.structure}")
        return False, reasons
    return True, reasons


def _check_breakout(
    snapshot: MarketStateSnapshot,
    narrative_tail: List[Dict[str, Any]],
    failed_breakout_count: int,
) -> tuple[bool, List[str], str]:
    reasons: List[str] = []
    setup_type = "none"
    max_failed = int(getattr(settings, "structural_gate_max_failed_breakouts", 2) or 2)
    if failed_breakout_count >= max_failed:
        reasons.append(f"structural_failed_breakout_count={failed_breakout_count}")
        return False, reasons, setup_type

    recent_types = {e.get("event_type") for e in narrative_tail[-10:]}
    if snapshot.breakout_status == "confirmed":
        setup_type = "breakout"
        require_retest = bool(
            getattr(settings, "structural_gate_breakout_require_retest", True)
        )
        if require_retest and "retest_successful" not in recent_types:
            if snapshot.retest_status not in ("successful", "none"):
                reasons.append("structural_breakout_retest_pending")
                return False, reasons, setup_type
        return True, reasons, setup_type

    if snapshot.trend in ("bullish", "bearish") and snapshot.momentum in (
        "increasing",
        "flat",
    ):
        if "pullback_ends" in recent_types or snapshot.trend_strength != "weak":
            setup_type = "trend_continuation"
            return True, reasons, setup_type

    reasons.append("structural_no_valid_setup")
    return False, reasons, setup_type


def _check_liquidity(snapshot: MarketStateSnapshot) -> tuple[bool, List[str]]:
    if snapshot.liquidity == "stressed":
        return False, ["structural_liquidity_stressed"]
    if snapshot.liquidity == "thin":
        return False, ["structural_liquidity_thin"]
    return True, []


def _check_volatility(snapshot: MarketStateSnapshot, setup_type: str) -> tuple[bool, List[str]]:
    if setup_type == "breakout" and snapshot.volatility == "compressing":
        return False, ["structural_volatility_compressing_for_breakout"]
    return True, []


def _check_risk(
    *,
    symbol: str,
    has_open_position: bool,
    bar_index: int,
    direction: str,
    gate_state: Optional[V43GateState],
) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    if has_open_position and direction in ("LONG", "SHORT"):
        reasons.append("structural_risk_open_position")
        return False, reasons

    if gate_state is not None and direction == "LONG":
        gr = apply_post_threshold_gates(
            raw_long=True,
            regime="neutral",
            current_bar_index=bar_index,
            has_open_position=has_open_position,
            state=gate_state,
        )
        if not gr.allow:
            reasons.append(f"structural_risk_{gr.reject_reason or 'gate'}")
            return False, reasons
    elif gate_state is not None and direction == "SHORT":
        gr = apply_post_threshold_gates_short(
            raw_short=True,
            regime="neutral",
            current_bar_index=bar_index,
            has_open_position=has_open_position,
            state=gate_state,
        )
        if not gr.allow:
            reasons.append(f"structural_risk_{gr.reject_reason or 'gate'}")
            return False, reasons

    return True, reasons


class StructuralGateEngine:
    """Evaluates categorical structural gates for trade permission."""

    def evaluate(
        self,
        *,
        snapshot: MarketStateSnapshot,
        structure: Optional[MarketStructureSnapshot] = None,
        narrative_tail: Optional[List[Dict[str, Any]]] = None,
        failed_breakout_count: int = 0,
        has_open_position: bool = False,
        gate_state: Optional[V43GateState] = None,
        new_events: Optional[List[NarrativeEvent]] = None,
    ) -> StructuralGateResult:
        """Return structural permission across six categories."""
        tail = list(narrative_tail or [])
        if new_events:
            tail.extend(e.to_dict() for e in new_events)

        direction = snapshot.direction_bias
        categories: Dict[str, bool] = {}
        block_reasons: List[str] = []

        ok, r = _check_trend(snapshot)
        categories["trend"] = ok
        block_reasons.extend(r)

        ok, r = _check_structure(snapshot, structure)
        categories["structure"] = ok
        block_reasons.extend(r)

        ok, r, setup_type = _check_breakout(snapshot, tail, failed_breakout_count)
        categories["breakout"] = ok
        block_reasons.extend(r)

        ok, r = _check_liquidity(snapshot)
        categories["liquidity"] = ok
        block_reasons.extend(r)

        ok, r = _check_volatility(snapshot, setup_type)
        categories["volatility"] = ok
        block_reasons.extend(r)

        ok, r = _check_risk(
            symbol=snapshot.symbol,
            has_open_position=has_open_position,
            bar_index=snapshot.bar_index,
            direction=direction,
            gate_state=gate_state,
        )
        categories["risk"] = ok
        block_reasons.extend(r)

        trade_allowed = all(categories.get(c, False) for c in _CATEGORIES)
        result = StructuralGateResult(
            trade_allowed=trade_allowed,
            categories=categories,
            block_reasons=block_reasons,
            setup_type=setup_type if trade_allowed else "none",
        )
        logger.debug(
            "structural_gate_evaluated",
            symbol=snapshot.symbol,
            trade_allowed=trade_allowed,
            categories=categories,
            setup_type=result.setup_type,
        )
        return result


structural_gate_engine = StructuralGateEngine()
