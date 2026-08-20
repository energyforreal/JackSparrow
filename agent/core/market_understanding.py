"""Agent market understanding: per-TF views + climate/setup/timing synthesis.

ML models remain sensors. This module maps raw transformer heads into role-specific
views and synthesizes a long/short/flat thesis. Wire format for exchange handlers
stays BUY/SELL/HOLD (+ STRONG_*).

Role contract (only live decision path):
  - 1h/2h  → climate (permission)
  - 15m    → setup (thesis + SL/TP/size)
  - 30m    → confirm (STRONG / size only; never alternate entry)
  - 5m     → timing (with/against/quiet; never entry)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from feature_store.transformer_btcusd.contract import (
    CONTINUOUS_LABEL_COLS,
    DEFAULT_PATH_LABEL_HORIZON_MINUTES,
    RESOLUTION_MINUTES,
    candle_family_from_class,
    compute_long_edge,
    compute_path_edge,
    compute_short_edge,
)

# Role groupings
_CLIMATE_TFS = frozenset({"tf_1h", "tf_2h"})
_SETUP_TFS = frozenset({"tf_15m", "tf_30m"})
_TIMING_TFS = frozenset({"tf_5m"})

# Imbalance z thresholds (edge / typical_abs_edge)
_CLIMATE_LEAN_Z = 0.75
_SETUP_PATH_Z = 0.85
_TIMING_LEAN_Z = 0.60
_SETUP_STRONG_Z = 1.25

# "Stopped before the move" filter on 15m setup
_DRAWDOWN_FLAT_RATIO = 0.8
# Low trend + weak imbalance → do not invent a path
_SETUP_MIN_TREND_STRENGTH = 0.8
# Same-side OI rise can allow STRONG; opposing OI never flips thesis
_OI_CONFIRM_MIN = 0.01
_HIGH_VOL_SIZE_CAP = 0.70

_MFE_IDX = CONTINUOUS_LABEL_COLS.index("mfe")
_MAE_IDX = CONTINUOUS_LABEL_COLS.index("mae")


def resolution_to_tf_key(resolution: str) -> str:
    """Map resolution string (e.g. ``15m``) to ``tf_15m``."""
    res = str(resolution or "").strip().lower()
    return f"tf_{res}"


def resolution_to_ctx_key(resolution: str) -> str:
    """Map resolution to orchestrator frame key (e.g. ``15m`` → ``v43_df15m``)."""
    res = str(resolution or "").strip().lower()
    return f"v43_df{res}"


@dataclass
class TfMarketView:
    """Per-timeframe market description (not a trade signal)."""

    tf_key: str
    resolution: str
    horizon_minutes: int
    mfe: float
    mae: float
    path_edge: float
    long_edge: float
    short_edge: float
    path_imbalance_z: float
    typical_abs_edge: float
    vol_regime: str
    future_volatility: float
    trend_strength: float
    quality: str
    risk: str
    drawdown_before_mfe: float = 0.0
    future_oi_change_pct: float = 0.0
    imbalance_ratio: float = 0.0
    climate_stance: Optional[str] = None  # long|short|two_sided|crisis
    setup_stance: Optional[str] = None  # long_path|short_path|flat
    timing_stance: Optional[str] = None  # with|against|quiet
    model_name: str = ""
    confidence: float = 0.0
    structure_outcome: str = ""
    future_candle_class: int = -1
    future_candle_name: str = ""
    candle_follow_through_atr: float = 0.0
    structure_delta: float = 0.0
    next_direction: int = -1
    next_wick: int = -1
    volume_confirms: float = 1.0
    pattern_validates: float = 1.0
    horizon_t24_dir: int = -1
    horizon_ladder: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MarketState:
    """Agent thesis from climate x setup x timing."""

    climate: str  # long|short|two_sided|conflicted|crisis|unknown
    setup: str  # long_path|short_path|flat
    timing: str  # with|against|quiet
    thesis: str  # long|short|flat
    wire_signal: str  # BUY|SELL|HOLD|STRONG_BUY|STRONG_SELL
    confidence: float
    reason_codes: List[str] = field(default_factory=list)
    primary_tf: str = ""
    size_scale: float = 0.0
    mfe: float = 0.0
    mae: float = 0.0
    long_edge: float = 0.0
    short_edge: float = 0.0
    winning_edge: float = 0.0
    future_volatility: float = 0.0
    vol_regime: str = "NORMAL"
    path_edge: float = 0.0
    threshold: float = 0.005
    views: Dict[str, TfMarketView] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "climate": self.climate,
            "setup": self.setup,
            "timing": self.timing,
            "thesis": self.thesis,
            "wire_signal": self.wire_signal,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "primary_tf": self.primary_tf,
            "size_scale": self.size_scale,
            "mfe": self.mfe,
            "mae": self.mae,
            "long_edge": self.long_edge,
            "short_edge": self.short_edge,
            "winning_edge": self.winning_edge,
            "future_volatility": self.future_volatility,
            "vol_regime": self.vol_regime,
            "path_edge": self.path_edge,
            "threshold": self.threshold,
            "views": {k: v.to_dict() for k, v in self.views.items()},
        }


def _resolution_from_tf_key(tf_key: str) -> str:
    if tf_key.startswith("tf_"):
        return tf_key[3:]
    return tf_key


def _horizon_minutes(resolution: str, bundle_metadata: Mapping[str, Any]) -> int:
    bars = bundle_metadata.get("path_label_horizon_bars")
    minutes = RESOLUTION_MINUTES.get(resolution)
    if bars is not None and minutes is not None:
        try:
            return int(bars) * int(minutes)
        except (TypeError, ValueError):
            pass
    return int(DEFAULT_PATH_LABEL_HORIZON_MINUTES.get(resolution, 240))


def typical_abs_edge_from_metadata(bundle_metadata: Mapping[str, Any]) -> float:
    """Typical |mfe - mae| scale from bundle label_mean/label_std."""
    means = bundle_metadata.get("label_mean")
    stds = bundle_metadata.get("label_std")
    typical = 0.005
    if isinstance(means, (list, tuple)) and len(means) > max(_MFE_IDX, _MAE_IDX):
        try:
            mfe_m = float(means[_MFE_IDX])
            mae_m = float(means[_MAE_IDX])
            # Near-symmetric means => use combined std as typical edge scale
            typical = abs(mfe_m - mae_m)
        except (TypeError, ValueError):
            typical = 0.0
    if typical < 1e-4 and isinstance(stds, (list, tuple)) and len(stds) > max(_MFE_IDX, _MAE_IDX):
        try:
            typical = 0.5 * (float(stds[_MFE_IDX]) + float(stds[_MAE_IDX]))
        except (TypeError, ValueError):
            typical = 0.005
    if typical < 1e-4:
        thr = bundle_metadata.get("default_threshold")
        try:
            typical = float(thr) if thr is not None else 0.005
        except (TypeError, ValueError):
            typical = 0.005
    return float(max(typical, 1e-4))


def _imbalance_ratio(mfe: float, mae: float) -> float:
    denom = float(mfe) + float(mae)
    if denom <= 1e-12:
        return 0.0
    return float((float(mfe) - float(mae)) / denom)


def _quality_label(
    trend_strength: float,
    mfe: float,
    mae: float,
    *,
    follow_through: float = 0.0,
    structure_delta: float = 0.0,
) -> str:
    ratio = mfe / (mae + 1e-6)
    if trend_strength >= 1.5 and ratio >= 1.5:
        if follow_through < 0.0:
            return "medium"
        if (mfe > mae and structure_delta < -0.25) or (
            mae > mfe and structure_delta > 0.25
        ):
            return "medium"
        return "high"
    if trend_strength >= 0.8 or ratio >= 1.0:
        return "medium"
    return "low"


def _risk_label(vol_regime: str) -> str:
    label = str(vol_regime or "NORMAL").upper()
    if label == "EXTREME":
        return "extreme"
    if label == "HIGH":
        return "elevated"
    return "normal"


def _setup_strength(view: TfMarketView) -> float:
    return float(min(1.0, max(0.0, abs(view.path_imbalance_z) / _SETUP_STRONG_Z)))


def _apply_setup_filters(
    *,
    tf_key: str,
    setup_stance: Optional[str],
    imbalance_z: float,
    trend_strength: float,
    mae: float,
    drawdown_before_mfe: float,
    structure_outcome: str = "",
) -> tuple[Optional[str], List[str]]:
    """Flatten weak / high-pain 15m setups. 30m stays raw for confirmation only."""
    codes: List[str] = []
    if setup_stance is None or setup_stance == "flat":
        return setup_stance, codes
    if tf_key != "tf_15m":
        return setup_stance, codes

    if abs(imbalance_z) < _SETUP_PATH_Z:
        return "flat", codes

    outcome = str(structure_outcome or "").upper()
    if outcome in ("FAILED_BREAK", "REVERSAL"):
        codes.append(f"setup_15m_{outcome.lower()}_flat")
        return "flat", codes

    if trend_strength < _SETUP_MIN_TREND_STRENGTH and abs(imbalance_z) < _SETUP_STRONG_Z:
        codes.append("setup_15m_low_trend_flat")
        return "flat", codes

    mae_safe = max(float(mae), 1e-9)
    dd_ratio = float(drawdown_before_mfe) / mae_safe
    if dd_ratio >= _DRAWDOWN_FLAT_RATIO:
        codes.append("setup_15m_drawdown_flat")
        return "flat", codes

    return setup_stance, codes


def _timing_from_short_horizons(
    *,
    setup_direction: Optional[str],
    h5m_dir: int,
    h10m_dir: int,
    imbalance_z: float,
) -> str:
    """5m timing from 5m+10m direction packets (v8). Never uses 15m–2h heads."""
    if setup_direction not in ("long", "short"):
        return "quiet"

    def _align(direction: int) -> str:
        if int(direction) < 0 or int(direction) == 1:
            return "quiet"
        if setup_direction == "long":
            return "with" if int(direction) == 2 else "against"
        return "with" if int(direction) == 0 else "against"

    t5 = _align(int(h5m_dir))
    t10 = _align(int(h10m_dir))
    if t5 == "against" or t10 == "against":
        return "against"
    if t5 == "with" or t10 == "with":
        return "with"
    if abs(imbalance_z) < _TIMING_LEAN_Z:
        return "quiet"
    if setup_direction == "long":
        return "with" if imbalance_z > 0 else "against"
    return "with" if imbalance_z < 0 else "against"


def _timing_from_z_and_candle(
    *,
    setup_direction: Optional[str],
    imbalance_z: float,
    future_candle_class: int,
    next_direction: int = -1,
    next_wick: int = -1,
    volume_confirms: float = 1.0,
    pattern_validates: float = 1.0,
) -> str:
    """5m timing from path z, next-candle structure, and volume/chart gates."""
    if setup_direction not in ("long", "short"):
        return "quiet"
    if float(volume_confirms) < 0.5 or float(pattern_validates) < 0.5:
        return "quiet"
    if abs(imbalance_z) < _TIMING_LEAN_Z:
        timing = "quiet"
    elif setup_direction == "long":
        timing = "with" if imbalance_z > 0 else "against"
    else:
        timing = "with" if imbalance_z < 0 else "against"
    if int(next_direction) >= 0:
        if int(next_direction) == 1:
            if int(next_wick) == 2 and setup_direction == "long":
                return "with"
            if int(next_wick) == 1 and setup_direction == "short":
                return "with"
            return "quiet"
        if setup_direction == "long":
            return "with" if int(next_direction) == 2 else "against"
        return "with" if int(next_direction) == 0 else "against"
    if int(future_candle_class) < 0:
        return timing
    family = candle_family_from_class(int(future_candle_class))
    if family == "doji":
        return "quiet"
    if setup_direction == "long":
        return "with" if family == "bull" else "against"
    return "with" if family == "bear" else "against"


def build_tf_market_view(
    *,
    tf_key: str,
    prediction_context: Mapping[str, Any],
    bundle_metadata: Mapping[str, Any],
    model_name: str = "",
    setup_direction: Optional[str] = None,
) -> TfMarketView:
    """Map one transformer prediction context to a role-specific market view.

    Does not emit BUY/SELL. ``setup_direction`` is ``long``|``short``|None and is
    only used for the 5m timing stance.
    """
    resolution = _resolution_from_tf_key(tf_key)
    continuous = prediction_context.get("transformer_continuous_preds") or {}
    mfe = float(
        continuous.get("mfe", continuous.get("h5m_mfe", prediction_context.get("mfe", 0.0)))
        or 0.0
    )
    mae = float(
        continuous.get("mae", continuous.get("h5m_mae", prediction_context.get("mae", 0.0)))
        or 0.0
    )
    long_edge = float(
        prediction_context.get("long_edge")
        if prediction_context.get("long_edge") is not None
        else compute_long_edge(mfe, mae)
    )
    short_edge = float(
        prediction_context.get("short_edge")
        if prediction_context.get("short_edge") is not None
        else compute_short_edge(mfe, mae)
    )
    path_edge = float(
        prediction_context.get("path_edge")
        if prediction_context.get("path_edge") is not None
        else compute_path_edge(mfe, mae)
    )
    vol_regime = str(
        prediction_context.get("transformer_vol_regime")
        or prediction_context.get("vol_regime")
        or "NORMAL"
    ).upper()
    future_vol = float(
        continuous.get("future_volatility", continuous.get("h5m_vol", 0.0)) or 0.0
    )
    trend_strength = float(
        continuous.get("trend_strength", continuous.get("h5m_trend_strength", 0.0)) or 0.0
    )
    drawdown_before_mfe = float(
        continuous.get("drawdown_before_mfe", 0.0) or 0.0
    )
    future_oi_change_pct = float(
        continuous.get("future_oi_change_pct", 0.0) or 0.0
    )
    follow_through = float(continuous.get("candle_follow_through_atr", 0.0) or 0.0)
    structure_delta = float(continuous.get("structure_delta", 0.0) or 0.0)
    structure_outcome = str(
        prediction_context.get("transformer_structure_outcome") or ""
    )
    future_candle_class = int(
        prediction_context.get("transformer_future_candle_class", -1) or -1
    )
    future_candle_name = str(
        prediction_context.get("transformer_future_candle_name") or ""
    )
    next_direction = int(prediction_context.get("next_direction", -1) or -1)
    next_wick = int(prediction_context.get("next_wick", -1) or -1)
    volume_confirms = float(prediction_context.get("volume_confirms", 1.0) or 0.0)
    pattern_validates = float(prediction_context.get("pattern_validates", 1.0) or 0.0)
    horizon_t24_dir = int(prediction_context.get("horizon_t24_dir", -1) or -1)
    raw_ladder = prediction_context.get("horizon_ladder") or {}
    horizon_ladder: Dict[str, Any] = dict(raw_ladder) if isinstance(raw_ladder, Mapping) else {}
    typical = typical_abs_edge_from_metadata(bundle_metadata)
    imbalance_z = float(path_edge) / typical
    imbalance_ratio = _imbalance_ratio(mfe, mae)

    climate_stance: Optional[str] = None
    setup_stance: Optional[str] = None
    timing_stance: Optional[str] = None

    if tf_key in _CLIMATE_TFS:
        if vol_regime == "EXTREME":
            climate_stance = "crisis"
        elif imbalance_z >= _CLIMATE_LEAN_Z:
            climate_stance = "long"
        elif imbalance_z <= -_CLIMATE_LEAN_Z:
            climate_stance = "short"
        else:
            climate_stance = "two_sided"
    elif tf_key in _SETUP_TFS:
        if imbalance_z >= _SETUP_PATH_Z:
            setup_stance = "long_path"
        elif imbalance_z <= -_SETUP_PATH_Z:
            setup_stance = "short_path"
        else:
            setup_stance = "flat"
        setup_stance, _ = _apply_setup_filters(
            tf_key=tf_key,
            setup_stance=setup_stance,
            imbalance_z=imbalance_z,
            trend_strength=trend_strength,
            mae=mae,
            drawdown_before_mfe=drawdown_before_mfe,
            structure_outcome=structure_outcome,
        )
    elif tf_key in _TIMING_TFS:
        if horizon_ladder:
            timing_stance = _timing_from_short_horizons(
                setup_direction=setup_direction,
                h5m_dir=int((horizon_ladder.get("h5m") or {}).get("dir", -1)),
                h10m_dir=int((horizon_ladder.get("h10m") or {}).get("dir", -1)),
                imbalance_z=imbalance_z,
            )
        else:
            timing_stance = _timing_from_z_and_candle(
                setup_direction=setup_direction,
                imbalance_z=imbalance_z,
                future_candle_class=future_candle_class,
                next_direction=next_direction,
                next_wick=next_wick,
                volume_confirms=volume_confirms,
                pattern_validates=pattern_validates,
            )

    conf = float(min(1.0, abs(imbalance_z) / max(_SETUP_STRONG_Z, 1e-6)))
    return TfMarketView(
        tf_key=tf_key,
        resolution=resolution,
        horizon_minutes=_horizon_minutes(resolution, bundle_metadata),
        mfe=mfe,
        mae=mae,
        path_edge=path_edge,
        long_edge=long_edge,
        short_edge=short_edge,
        path_imbalance_z=imbalance_z,
        typical_abs_edge=typical,
        vol_regime=vol_regime,
        future_volatility=future_vol,
        trend_strength=trend_strength,
        quality=_quality_label(
            trend_strength,
            mfe,
            mae,
            follow_through=follow_through,
            structure_delta=structure_delta,
        ),
        risk=_risk_label(vol_regime),
        drawdown_before_mfe=drawdown_before_mfe,
        future_oi_change_pct=future_oi_change_pct,
        imbalance_ratio=imbalance_ratio,
        climate_stance=climate_stance,
        setup_stance=setup_stance,
        timing_stance=timing_stance,
        model_name=model_name,
        confidence=conf,
        structure_outcome=structure_outcome,
        future_candle_class=future_candle_class,
        future_candle_name=future_candle_name,
        candle_follow_through_atr=follow_through,
        structure_delta=structure_delta,
        next_direction=next_direction,
        next_wick=next_wick,
        volume_confirms=volume_confirms,
        pattern_validates=pattern_validates,
        horizon_t24_dir=horizon_t24_dir,
        horizon_ladder=horizon_ladder,
    )


def _resolve_climate(
    views: Mapping[str, TfMarketView],
) -> tuple[str, List[str]]:
    codes: List[str] = []
    c1 = views.get("tf_1h")
    c2 = views.get("tf_2h")
    stances = []
    for v in (c1, c2):
        if v is not None and v.climate_stance:
            stances.append(v.climate_stance)

    if any(s == "crisis" for s in stances):
        codes.append("climate_crisis")
        return "crisis", codes

    if not stances:
        codes.append("climate_unknown")
        return "unknown", codes

    longs = sum(1 for s in stances if s == "long")
    shorts = sum(1 for s in stances if s == "short")
    two = sum(1 for s in stances if s == "two_sided")

    if longs and shorts:
        codes.append("climate_conflicted")
        return "conflicted", codes
    if longs and not shorts:
        codes.append("climate_long")
        return "long", codes
    if shorts and not longs:
        codes.append("climate_short")
        return "short", codes
    if two == len(stances):
        codes.append("climate_ranging")
        return "two_sided", codes
    codes.append("climate_ranging")
    return "two_sided", codes


def _thesis_to_wire(thesis: str, *, strong: bool) -> str:
    if thesis == "long":
        return "STRONG_BUY" if strong else "BUY"
    if thesis == "short":
        return "STRONG_SELL" if strong else "SELL"
    return "HOLD"


def _telemetry_from_15m(
    views: Mapping[str, TfMarketView],
) -> Dict[str, float]:
    """Preserve 15m path stats on HOLD for logging (never invent zero edge)."""
    setup_15 = views.get("tf_15m")
    if setup_15 is None:
        return {
            "mfe": 0.0,
            "mae": 0.0,
            "long_edge": 0.0,
            "short_edge": 0.0,
            "winning_edge": 0.0,
            "future_volatility": 0.0,
            "path_edge": 0.0,
            "threshold": 0.005,
        }
    winning = max(float(setup_15.long_edge), float(setup_15.short_edge))
    return {
        "mfe": float(setup_15.mfe),
        "mae": float(setup_15.mae),
        "long_edge": float(setup_15.long_edge),
        "short_edge": float(setup_15.short_edge),
        "winning_edge": float(winning),
        "future_volatility": float(setup_15.future_volatility),
        "path_edge": float(setup_15.path_edge),
        "threshold": float(setup_15.typical_abs_edge),
    }


def _oi_allows_strong(setup_dir: str, setup_15: TfMarketView) -> bool:
    oi = float(setup_15.future_oi_change_pct)
    if setup_dir == "long":
        return oi >= _OI_CONFIRM_MIN
    if setup_dir == "short":
        return oi <= -_OI_CONFIRM_MIN
    return False


def synthesize_agent_decision(
    views: Mapping[str, TfMarketView],
) -> MarketState:
    """Synthesize climate x setup x timing into wire signal + execution fields."""
    reason_codes: List[str] = []
    view_map = dict(views)

    climate, climate_codes = _resolve_climate(view_map)
    reason_codes.extend(climate_codes)

    tele = _telemetry_from_15m(view_map)
    empty = MarketState(
        climate=climate,
        setup="flat",
        timing="quiet",
        thesis="flat",
        wire_signal="HOLD",
        confidence=0.0,
        reason_codes=reason_codes,
        primary_tf="tf_15m",
        views=view_map,
        vol_regime=str(
            (view_map.get("tf_15m").vol_regime if view_map.get("tf_15m") else "NORMAL")
        ),
        **tele,
    )

    if climate == "crisis":
        return empty

    if climate in ("two_sided", "conflicted", "unknown"):
        return empty

    setup_15 = view_map.get("tf_15m")
    setup_30 = view_map.get("tf_30m")
    if setup_15 is None or setup_15.setup_stance is None:
        reason_codes.append("setup_15m_missing")
        empty.reason_codes = reason_codes
        return empty

    # Re-apply 15m filters with reason codes for synthesis audit
    filtered_setup, filter_codes = _apply_setup_filters(
        tf_key="tf_15m",
        setup_stance=setup_15.setup_stance,
        imbalance_z=setup_15.path_imbalance_z,
        trend_strength=setup_15.trend_strength,
        mae=setup_15.mae,
        drawdown_before_mfe=setup_15.drawdown_before_mfe,
        structure_outcome=setup_15.structure_outcome,
    )
    reason_codes.extend(filter_codes)
    setup_15.setup_stance = filtered_setup
    setup = filtered_setup or "flat"

    if setup == "flat":
        reason_codes.append("setup_15m_flat")
        empty.reason_codes = reason_codes
        empty.setup = "flat"
        return empty

    setup_dir = "long" if setup == "long_path" else "short"
    if (climate == "long" and setup_dir != "long") or (
        climate == "short" and setup_dir != "short"
    ):
        reason_codes.append("setup_fights_climate")
        empty.reason_codes = reason_codes
        empty.setup = setup
        return empty

    reason_codes.append(f"setup_15m_{setup}")
    outcome = str(setup_15.structure_outcome or "").upper()
    if outcome in ("BREAKOUT", "CONTINUATION_LONG") and setup_dir == "long":
        reason_codes.append("structure_confirms_setup")
    if outcome in ("BREAKOUT", "CONTINUATION_SHORT") and setup_dir == "short":
        reason_codes.append("structure_confirms_setup")

    timing_view = view_map.get("tf_5m")
    timing = "quiet"
    if timing_view is not None:
        ladder = dict(timing_view.horizon_ladder or {})
        if not ladder:
            if float(timing_view.volume_confirms) < 0.5 or float(
                timing_view.pattern_validates
            ) < 0.5:
                reason_codes.append("timing_chart_volume_gate")
                empty.setup = setup
                empty.timing = "quiet"
                empty.reason_codes = reason_codes
                return empty
            hz24 = int(timing_view.horizon_t24_dir)
            if hz24 >= 0 and climate in ("long", "short"):
                hz_long = hz24 == 2
                hz_short = hz24 == 0
                if (climate == "long" and hz_short) or (climate == "short" and hz_long):
                    reason_codes.append("timing_horizon_fights_climate")
                    empty.setup = setup
                    empty.timing = "against"
                    empty.reason_codes = reason_codes
                    return empty
            timing = _timing_from_z_and_candle(
                setup_direction=setup_dir,
                imbalance_z=timing_view.path_imbalance_z,
                future_candle_class=timing_view.future_candle_class,
                next_direction=timing_view.next_direction,
                next_wick=timing_view.next_wick,
                volume_confirms=timing_view.volume_confirms,
                pattern_validates=timing_view.pattern_validates,
            )
        else:
            timing = _timing_from_short_horizons(
                setup_direction=setup_dir,
                h5m_dir=int((ladder.get("h5m") or {}).get("dir", -1)),
                h10m_dir=int((ladder.get("h10m") or {}).get("dir", -1)),
                imbalance_z=timing_view.path_imbalance_z,
            )
        timing_view.timing_stance = timing
        reason_codes.append(f"timing_{timing}")
    else:
        reason_codes.append("timing_missing_quiet")

    if timing == "against":
        reason_codes.append("timing_against_flat")
        empty.setup = setup
        empty.timing = timing
        empty.reason_codes = reason_codes
        return empty

    # 30m confirms only — never opens risk on its own
    strong = False
    if setup_30 is not None and setup_30.setup_stance:
        if setup_30.setup_stance == setup:
            reason_codes.append("setup_30m_aligned")
            if abs(setup_15.path_imbalance_z) >= _SETUP_STRONG_Z:
                strong = True
                reason_codes.append("setup_strong_commitment")
        elif setup_30.setup_stance == "flat":
            reason_codes.append("setup_30m_flat_cap")
            strong = False
        else:
            reason_codes.append("setup_30m_opposed_cap")
            strong = False
    else:
        reason_codes.append("setup_30m_missing_cap")
        strong = False

    if timing == "quiet":
        strong = False
        reason_codes.append("timing_quiet_no_strong")

    # OI confirm-only: opposing OI blocks STRONG; same-side rise can keep it
    if strong:
        if _oi_allows_strong(setup_dir, setup_15):
            reason_codes.append("oi_confirms_strong")
        else:
            oi = float(setup_15.future_oi_change_pct)
            opposing = (setup_dir == "long" and oi < -_OI_CONFIRM_MIN) or (
                setup_dir == "short" and oi > _OI_CONFIRM_MIN
            )
            if opposing:
                strong = False
                reason_codes.append("oi_opposing_cap_strong")
            else:
                reason_codes.append("oi_neutral_strong_ok")

    thesis = setup_dir  # long|short
    wire = _thesis_to_wire(thesis, strong=strong)

    setup_conf = _setup_strength(setup_15)
    climate_agree = 1.0
    if climate in ("long", "short"):
        n_climate = sum(
            1
            for k in ("tf_1h", "tf_2h")
            if view_map.get(k) and view_map[k].climate_stance == climate
        )
        climate_agree = 0.7 + 0.15 * n_climate
    timing_factor = 1.0 if timing == "with" else 0.85
    confidence = float(min(1.0, setup_conf * climate_agree * timing_factor))

    size_scale = 1.0 if confidence >= 0.55 else max(0.35, confidence / 0.55)
    if timing == "quiet":
        size_scale = min(size_scale, 0.85)
    if str(setup_15.vol_regime).upper() == "HIGH":
        size_scale = min(size_scale, _HIGH_VOL_SIZE_CAP)
        reason_codes.append("high_vol_size_cap")

    winning = (
        setup_15.long_edge
        if setup_dir == "long"
        else setup_15.short_edge
    )
    return MarketState(
        climate=climate,
        setup=setup,
        timing=timing,
        thesis=thesis,
        wire_signal=wire,
        confidence=confidence,
        reason_codes=reason_codes,
        primary_tf="tf_15m",
        size_scale=float(size_scale),
        mfe=float(setup_15.mfe),
        mae=float(setup_15.mae),
        long_edge=float(setup_15.long_edge),
        short_edge=float(setup_15.short_edge),
        winning_edge=float(winning),
        future_volatility=float(setup_15.future_volatility),
        vol_regime=str(setup_15.vol_regime),
        path_edge=float(setup_15.path_edge),
        threshold=float(setup_15.typical_abs_edge),
        views=view_map,
    )


def build_views_from_predictions(
    *,
    predictions: Sequence[Any],
    model_registry: Any,
    resolution_to_tf_key_fn: Any = None,
) -> Dict[str, TfMarketView]:
    """Build views from MCP predictions; timing uses provisional then re-synth."""
    to_tf = resolution_to_tf_key_fn or resolution_to_tf_key
    provisional: Dict[str, TfMarketView] = {}
    meta_by_tf: Dict[str, Dict[str, Any]] = {}
    ctx_by_tf: Dict[str, Dict[str, Any]] = {}
    name_by_tf: Dict[str, str] = {}

    for pred in predictions:
        if str(getattr(pred, "health_status", "") or "").lower() != "healthy":
            continue
        pctx = pred.context if isinstance(getattr(pred, "context", None), dict) else {}
        tf_key = str(pctx.get("tf_key") or "")
        if not tf_key:
            node = model_registry.get_model(pred.model_name) if model_registry else None
            if node is not None and hasattr(node, "resolution"):
                tf_key = to_tf(getattr(node, "resolution"))
            else:
                continue
        bundle_metadata: Dict[str, Any] = {}
        node = model_registry.get_model(pred.model_name) if model_registry else None
        if node is not None and hasattr(node, "_bundle_metadata"):
            raw_meta = getattr(node, "_bundle_metadata")
            if isinstance(raw_meta, dict):
                bundle_metadata = raw_meta
        meta_by_tf[tf_key] = bundle_metadata
        ctx_by_tf[tf_key] = pctx
        name_by_tf[tf_key] = str(getattr(pred, "model_name", "") or "")
        provisional[tf_key] = build_tf_market_view(
            tf_key=tf_key,
            prediction_context=pctx,
            bundle_metadata=bundle_metadata,
            model_name=name_by_tf[tf_key],
            setup_direction=None,
        )

    setup_15 = provisional.get("tf_15m")
    setup_dir: Optional[str] = None
    if setup_15 and setup_15.setup_stance == "long_path":
        setup_dir = "long"
    elif setup_15 and setup_15.setup_stance == "short_path":
        setup_dir = "short"

    if "tf_5m" in ctx_by_tf:
        provisional["tf_5m"] = build_tf_market_view(
            tf_key="tf_5m",
            prediction_context=ctx_by_tf["tf_5m"],
            bundle_metadata=meta_by_tf.get("tf_5m") or {},
            model_name=name_by_tf.get("tf_5m", ""),
            setup_direction=setup_dir,
        )
    return provisional
