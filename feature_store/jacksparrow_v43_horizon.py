"""JackSparrow v43 prediction horizon and execution alignment helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Mapping, Optional

V43_CANDLE_MINUTES = 5

# Intraday multi-head horizons (5m bars).
V43_MULTIHEAD_FORWARD_BARS = frozenset({2, 6, 12, 24})
V43_SUPPORTED_FORWARD_TARGET_BARS = V43_MULTIHEAD_FORWARD_BARS

# Primary execution / thesis default (scalp 10m).
V43_FORWARD_TARGET_BARS_DEFAULT = 2


@dataclass(frozen=True)
class V43HorizonProfile:
    """Maps ML label horizon to suggested runtime execution parameters."""

    forward_bars: int
    horizon_minutes: int
    trade_debounce_bars: int
    max_position_hold_hours: float
    take_profit_pct: float
    label: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_PROFILES: Dict[int, V43HorizonProfile] = {
    2: V43HorizonProfile(
        forward_bars=2,
        horizon_minutes=10,
        trade_debounce_bars=1,
        max_position_hold_hours=0.5,
        take_profit_pct=0.006,
        label="scalp_10m",
    ),
    6: V43HorizonProfile(
        forward_bars=6,
        horizon_minutes=30,
        trade_debounce_bars=2,
        max_position_hold_hours=1.5,
        take_profit_pct=0.01,
        label="intraday_30m",
    ),
    12: V43HorizonProfile(
        forward_bars=12,
        horizon_minutes=60,
        trade_debounce_bars=3,
        max_position_hold_hours=2.5,
        take_profit_pct=0.012,
        label="intraday_1h",
    ),
    24: V43HorizonProfile(
        forward_bars=24,
        horizon_minutes=120,
        trade_debounce_bars=6,
        max_position_hold_hours=4.0,
        take_profit_pct=0.018,
        label="swing_2h",
    ),
}

# Thesis rule family -> intended hold horizon (5m bars).
THESIS_TYPE_FORWARD_BARS: Dict[str, int] = {
    "mean_reversion": 2,
    "breakout": 12,
    "trend_continuation": 6,
    "basis_crowding": 12,
    "funding_crowding": 12,
    "flat": 6,
    "crisis_veto": 6,
}


def forward_bars_to_minutes(forward_bars: int, *, candle_minutes: int = V43_CANDLE_MINUTES) -> int:
    return int(forward_bars) * int(candle_minutes)


def normalize_forward_bars(value: Any, *, default: int = V43_FORWARD_TARGET_BARS_DEFAULT) -> int:
    try:
        bars = int(value)
    except (TypeError, ValueError):
        bars = int(default)
    if bars in V43_SUPPORTED_FORWARD_TARGET_BARS:
        return bars
    return int(default)


def resolve_training_forward_bars(
    meta: Optional[Mapping[str, Any]] = None,
    *,
    settings_fallback: Optional[int] = None,
) -> int:
    """Primary execution horizon from multi-head metadata."""
    if meta is not None:
        peh = meta.get("primary_execution_horizon_bars")
        if peh is not None:
            return normalize_forward_bars(peh)
        legacy = meta.get("training_forward_bars")
        if legacy is not None:
            return normalize_forward_bars(legacy)
    if settings_fallback is not None:
        return normalize_forward_bars(settings_fallback)
    return V43_FORWARD_TARGET_BARS_DEFAULT


def horizon_profile(forward_bars: int) -> V43HorizonProfile:
    bars = normalize_forward_bars(forward_bars)
    return _PROFILES[bars]


def build_execution_profile(
    forward_bars: int,
    *,
    align: bool = True,
    debounce_override: Optional[int] = None,
    max_hold_hours_override: Optional[float] = None,
    take_profit_pct_override: Optional[float] = None,
) -> Dict[str, Any]:
    """Execution hints derived from the model label horizon."""
    prof = horizon_profile(forward_bars)
    debounce = (
        int(debounce_override)
        if debounce_override is not None
        else prof.trade_debounce_bars
    )
    max_hold = (
        float(max_hold_hours_override)
        if max_hold_hours_override is not None
        else prof.max_position_hold_hours
    )
    tp_pct = (
        float(take_profit_pct_override)
        if take_profit_pct_override is not None
        else prof.take_profit_pct
    )
    return {
        "enabled": bool(align),
        "forward_bars": prof.forward_bars,
        "horizon_minutes": prof.horizon_minutes,
        "horizon_label": prof.label,
        "trade_debounce_bars": debounce,
        "max_position_hold_hours": max_hold,
        "take_profit_pct": tp_pct,
        "candle_minutes": V43_CANDLE_MINUTES,
    }


def thesis_intended_forward_bars(thesis_type: str) -> int:
    key = str(thesis_type or "flat").strip().lower()
    return THESIS_TYPE_FORWARD_BARS.get(key, V43_FORWARD_TARGET_BARS_DEFAULT)


def horizons_compatible(
    ml_forward_bars: int,
    thesis_forward_bars: int,
    *,
    strict: bool = True,
) -> bool:
    """True when thesis intended horizon matches the loaded ML label horizon."""
    ml_b = normalize_forward_bars(ml_forward_bars)
    th_b = normalize_forward_bars(thesis_forward_bars)
    if strict:
        return ml_b == th_b
    return abs(ml_b - th_b) <= 6


def validate_metadata_forward_bars(meta: Mapping[str, Any]) -> int:
    """Return primary execution horizon; raise if metadata specifies unsupported bars."""
    peh = meta.get("primary_execution_horizon_bars", meta.get("training_forward_bars"))
    if peh is None:
        return V43_FORWARD_TARGET_BARS_DEFAULT
    try:
        bars = int(peh)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"v43 metadata forward bars invalid: {peh!r}") from exc
    if bars not in V43_SUPPORTED_FORWARD_TARGET_BARS:
        raise ValueError(
            f"v43 metadata forward_bars={bars} not in {sorted(V43_SUPPORTED_FORWARD_TARGET_BARS)}"
        )
    return bars


