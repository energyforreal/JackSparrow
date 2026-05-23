"""Portfolio intelligence guard — heat, concentration, and correlation caps.

Staged rollout (see ``.env.example``):
  1. ``PORTFOLIO_INTELLIGENCE_ENABLED=true`` + ``SHADOW_MODE=true`` — log only
  2. ``SHADOW_MODE=false``, ``REDUCE_ENABLED=true`` — downsize near limits
  3. ``BLOCK_ENABLED=true`` on testnet — full enforcement
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

import structlog

from agent.core.config import settings
from agent.events.schemas import PolicyVerdict

logger = structlog.get_logger()

GuardAction = Literal["allow", "reduce_size", "block"]

_ENTRY_BUY = frozenset({"BUY", "STRONG_BUY"})
_ENTRY_SELL = frozenset({"SELL", "STRONG_SELL"})


@dataclass
class PortfolioPositionRow:
    """Normalized open position for portfolio guard."""

    symbol: str
    side: str  # LONG | SHORT
    notional_usd: float
    leverage: Optional[float] = None
    unrealized_pnl_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "notional_usd": self.notional_usd,
            "leverage": self.leverage,
            "unrealized_pnl_usd": self.unrealized_pnl_usd,
        }


@dataclass
class PortfolioExposureSnapshot:
    """Current book state used for pre-trade portfolio checks."""

    portfolio_equity_usd: float
    positions: List[PortfolioPositionRow] = field(default_factory=list)
    source: str = "unknown"

    @property
    def total_open_notional_usd(self) -> float:
        return float(sum(max(0.0, p.notional_usd) for p in self.positions))

    @property
    def long_notional_usd(self) -> float:
        return float(
            sum(
                max(0.0, p.notional_usd)
                for p in self.positions
                if str(p.side).upper() == "LONG"
            )
        )

    @property
    def short_notional_usd(self) -> float:
        return float(
            sum(
                max(0.0, p.notional_usd)
                for p in self.positions
                if str(p.side).upper() == "SHORT"
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portfolio_equity_usd": self.portfolio_equity_usd,
            "total_open_notional_usd": self.total_open_notional_usd,
            "long_notional_usd": self.long_notional_usd,
            "short_notional_usd": self.short_notional_usd,
            "open_position_count": len(self.positions),
            "source": self.source,
            "positions": [p.to_dict() for p in self.positions],
        }


@dataclass
class PortfolioGuardDecision:
    """Outcome of portfolio guard evaluation."""

    action: GuardAction
    allowed_size_fraction: float
    heat_ratio: float
    side_concentration_ratio: float
    correlation_group: Optional[str] = None
    correlation_group_notional_usd: float = 0.0
    reason_codes: List[str] = field(default_factory=list)
    shadow_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "allowed_size_fraction": self.allowed_size_fraction,
            "heat_ratio": self.heat_ratio,
            "side_concentration_ratio": self.side_concentration_ratio,
            "correlation_group": self.correlation_group,
            "correlation_group_notional_usd": self.correlation_group_notional_usd,
            "reason_codes": list(self.reason_codes),
            "shadow_only": self.shadow_only,
        }


def _coerce_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _signal_side(signal: str) -> Optional[str]:
    s = str(signal or "").upper()
    if s in _ENTRY_BUY:
        return "LONG"
    if s in _ENTRY_SELL:
        return "SHORT"
    return None


def _parse_correlation_groups() -> Dict[str, List[str]]:
    raw = getattr(settings, "portfolio_correlation_groups_json", None)
    if isinstance(raw, dict):
        out: Dict[str, List[str]] = {}
        for k, vals in raw.items():
            if isinstance(vals, list):
                out[str(k)] = [str(x).upper() for x in vals]
        return out
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {
                    str(k): [str(x).upper() for x in v]
                    for k, v in parsed.items()
                    if isinstance(v, list)
                }
        except json.JSONDecodeError:
            pass
    return {
        "crypto_major": ["BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"],
    }


def _correlation_group_for_symbol(
    symbol: str, groups: Dict[str, List[str]]
) -> Optional[str]:
    sym = str(symbol or "").upper()
    for name, members in groups.items():
        if sym in {m.upper() for m in members}:
            return name
    return None


def _row_from_dict(row: Dict[str, Any]) -> Optional[PortfolioPositionRow]:
    sym = str(row.get("symbol") or row.get("product_symbol") or "").upper()
    if not sym:
        return None
    side_raw = str(row.get("side") or "").upper()
    if side_raw in ("LONG", "BUY"):
        side = "LONG"
    elif side_raw in ("SHORT", "SELL"):
        side = "SHORT"
    else:
        try:
            signed = _coerce_float(row.get("size") or row.get("quantity") or row.get("lots"))
            side = "LONG" if signed >= 0 else "SHORT"
        except Exception:
            side = "LONG"
    notional = _coerce_float(row.get("notional_usd") or row.get("notional"))
    if notional <= 0:
        entry = _coerce_float(row.get("entry_price") or row.get("mark_price"))
        qty = abs(_coerce_float(row.get("quantity") or row.get("lots") or row.get("size")))
        notional = entry * qty if entry > 0 and qty > 0 else 0.0
    if notional <= 0:
        return None
    lev = row.get("leverage")
    try:
        leverage = float(lev) if lev is not None else None
    except (TypeError, ValueError):
        leverage = None
    return PortfolioPositionRow(
        symbol=sym,
        side=side,
        notional_usd=notional,
        leverage=leverage,
        unrealized_pnl_usd=_coerce_float(row.get("unrealized_pnl") or row.get("unrealized_pnl_usd")),
    )


def build_snapshot_from_context(context: Dict[str, Any]) -> PortfolioExposureSnapshot:
    """Build snapshot from orchestrator/market context (preferred when present)."""
    equity = _coerce_float(
        context.get("portfolio_value")
        or context.get("portfolio_equity_usd")
        or getattr(settings, "initial_balance", 10000.0),
        10000.0,
    )
    rows: List[PortfolioPositionRow] = []
    open_pos = context.get("open_positions")
    if isinstance(open_pos, list):
        for item in open_pos:
            if isinstance(item, dict):
                r = _row_from_dict(item)
                if r is not None:
                    rows.append(r)
    return PortfolioExposureSnapshot(
        portfolio_equity_usd=max(equity, 1.0),
        positions=rows,
        source="market_context",
    )


def build_snapshot_from_exchange_rows(
    rows: List[Dict[str, Any]],
    *,
    portfolio_equity_usd: float,
) -> PortfolioExposureSnapshot:
    """Normalize Delta margined-position rows into a snapshot."""
    parsed: List[PortfolioPositionRow] = []
    for row in rows:
        if isinstance(row, dict):
            r = _row_from_dict(row)
            if r is not None:
                parsed.append(r)
    return PortfolioExposureSnapshot(
        portfolio_equity_usd=max(portfolio_equity_usd, 1.0),
        positions=parsed,
        source="exchange",
    )


async def fetch_portfolio_exposure_snapshot(
    symbol: str,
    context: Optional[Dict[str, Any]] = None,
) -> PortfolioExposureSnapshot:
    """Context-first snapshot; enriches with exchange margined positions when available."""
    ctx = context if isinstance(context, dict) else {}
    snap = build_snapshot_from_context(ctx)
    equity = snap.portfolio_equity_usd

    try:
        from agent.core.execution import execution_module

        view = await execution_module.get_margined_positions_view()
        raw_rows = view.get("result") if isinstance(view, dict) else None
        if isinstance(raw_rows, list) and raw_rows:
            ex_snap = build_snapshot_from_exchange_rows(
                [r for r in raw_rows if isinstance(r, dict)],
                portfolio_equity_usd=equity,
            )
            if ex_snap.positions:
                snap = ex_snap
    except Exception as exc:
        logger.debug("portfolio_snapshot_exchange_fetch_failed", error=str(exc))

    if not snap.positions and symbol:
        sym = str(symbol).upper()
        if bool(ctx.get("has_open_position")):
            snap.positions.append(
                PortfolioPositionRow(
                    symbol=sym,
                    side="LONG",
                    notional_usd=max(snap.total_open_notional_usd, equity * 0.05),
                )
            )
    return snap


def evaluate_portfolio_guard(
    snapshot: PortfolioExposureSnapshot,
    *,
    symbol: str,
    proposed_signal: str,
    proposed_size_fraction: float,
) -> PortfolioGuardDecision:
    """Deterministic portfolio guard: heat, side concentration, correlation group."""
    enabled = bool(getattr(settings, "portfolio_intelligence_enabled", False))
    shadow = bool(getattr(settings, "portfolio_intelligence_shadow_mode", True))
    reduce_on = bool(getattr(settings, "portfolio_intelligence_reduce_enabled", False))
    block_on = bool(getattr(settings, "portfolio_intelligence_block_enabled", False))

    side = _signal_side(proposed_signal)
    size_frac = max(0.0, float(proposed_size_fraction or 0.0))
    reasons: List[str] = []

    if not enabled or side is None or size_frac <= 0:
        return PortfolioGuardDecision(
            action="allow",
            allowed_size_fraction=size_frac,
            heat_ratio=0.0,
            side_concentration_ratio=0.0,
            reason_codes=["portfolio_guard_skipped"],
            shadow_only=shadow,
        )

    equity = max(snapshot.portfolio_equity_usd, 1.0)
    current_notional = snapshot.total_open_notional_usd
    proposed_notional = size_frac * equity
    post_notional = current_notional + proposed_notional
    heat_ratio = post_notional / equity

    max_heat = float(getattr(settings, "portfolio_max_heat_ratio", 0.85) or 0.85)
    max_side_conc = float(
        getattr(settings, "portfolio_max_same_side_concentration", 0.70) or 0.70
    )
    max_group_frac = float(
        getattr(settings, "portfolio_max_correlation_group_fraction", 0.55) or 0.55
    )
    reduce_factor = float(
        getattr(settings, "portfolio_near_limit_size_factor", 0.50) or 0.50
    )
    reduce_band = float(getattr(settings, "portfolio_near_limit_band", 0.08) or 0.08)

    long_n = snapshot.long_notional_usd + (proposed_notional if side == "LONG" else 0.0)
    short_n = snapshot.short_notional_usd + (proposed_notional if side == "SHORT" else 0.0)
    total_dir = long_n + short_n
    if side == "LONG":
        side_conc = long_n / total_dir if total_dir > 0 else 0.0
    else:
        side_conc = short_n / total_dir if total_dir > 0 else 0.0

    action: GuardAction = "allow"
    allowed = size_frac
    corr_group: Optional[str] = None
    group_notional = 0.0

    if heat_ratio > max_heat:
        action = "block"
        reasons.append(
            f"portfolio_heat_cap:{heat_ratio:.3f}>{max_heat:.3f}"
        )
    elif heat_ratio > (max_heat - reduce_band):
        action = "reduce_size"
        allowed = size_frac * reduce_factor
        reasons.append(
            f"portfolio_heat_near_cap:{heat_ratio:.3f}"
        )

    if side_conc > max_side_conc:
        if action != "block":
            action = "block"
        reasons.append(
            f"portfolio_side_concentration:{side_conc:.3f}>{max_side_conc:.3f}"
        )

    groups = _parse_correlation_groups()
    corr_group = _correlation_group_for_symbol(symbol, groups)
    if corr_group:
        members = {m.upper() for m in groups[corr_group]}
        group_notional = sum(
            p.notional_usd for p in snapshot.positions if p.symbol in members
        )
        if str(symbol).upper() in members:
            group_notional += proposed_notional
        group_cap = max_group_frac * equity
        if group_notional > group_cap:
            if action == "allow":
                action = "reduce_size"
                allowed = min(allowed, size_frac * reduce_factor)
            if group_notional > group_cap * 1.05:
                action = "block"
            reasons.append(
                f"portfolio_corr_group_limit:{corr_group}:{group_notional:.0f}>{group_cap:.0f}"
            )

    if action == "allow":
        reasons.append("portfolio_guard_passed")

    enforce = enabled and not shadow and (reduce_on or block_on)
    effective_action: GuardAction = action
    if not enforce:
        effective_action = "allow"
        if action != "allow":
            reasons.append("portfolio_shadow_mode_no_enforce")
    elif action == "reduce_size" and not reduce_on:
        effective_action = "allow"
        reasons.append("portfolio_reduce_not_enforced")
    elif action == "block" and not block_on:
        effective_action = "allow"
        reasons.append("portfolio_block_not_enforced")

    if effective_action == "block":
        allowed = 0.0

    return PortfolioGuardDecision(
        action=effective_action,
        allowed_size_fraction=max(0.0, allowed),
        heat_ratio=heat_ratio,
        side_concentration_ratio=side_conc,
        correlation_group=corr_group,
        correlation_group_notional_usd=group_notional,
        reason_codes=reasons,
        shadow_only=shadow and not enforce,
    )


def apply_portfolio_guard_to_verdict(
    verdict: PolicyVerdict,
    guard: PortfolioGuardDecision,
    *,
    symbol: str,
) -> PolicyVerdict:
    """Apply guard outcome to policy verdict (block -> HOLD, reduce -> clamp size)."""
    sig = str(verdict.signal or "HOLD").upper()
    if guard.action == "block":
        return PolicyVerdict(
            signal="HOLD",
            confidence=float(verdict.confidence or 0.0),
            position_size=0.0,
            reason_codes=list(verdict.reason_codes)
            + list(guard.reason_codes)
            + ["portfolio_guard_blocked"],
            ml_evidence_id=verdict.ml_evidence_id,
            adopted_ml_candidate=False,
        )
    if guard.action == "reduce_size" and guard.allowed_size_fraction < float(
        verdict.position_size or 0.0
    ):
        return PolicyVerdict(
            signal=sig,
            confidence=float(verdict.confidence or 0.0),
            position_size=float(guard.allowed_size_fraction),
            reason_codes=list(verdict.reason_codes)
            + list(guard.reason_codes)
            + ["portfolio_guard_size_reduced"],
            ml_evidence_id=verdict.ml_evidence_id,
            adopted_ml_candidate=verdict.adopted_ml_candidate,
        )
    if guard.reason_codes and guard.action == "allow":
        return PolicyVerdict(
            signal=sig,
            confidence=float(verdict.confidence or 0.0),
            position_size=float(verdict.position_size or 0.0),
            reason_codes=list(verdict.reason_codes) + list(guard.reason_codes),
            ml_evidence_id=verdict.ml_evidence_id,
            adopted_ml_candidate=verdict.adopted_ml_candidate,
        )
    return verdict
