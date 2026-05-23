"""Multi-horizon ML evidence builders and policy validation rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from agent.core.config import settings
from feature_store.jacksparrow_v43_horizon import forward_bars_to_minutes
from feature_store.jacksparrow_v43_multihead import (
    V43_HORIZON_KEY_TO_BARS,
    V43_HORIZON_KEYS,
    V43_THESIS_CONFIRMATION_HEADS,
    V43_THESIS_OPPOSITION_HEADS,
    bars_to_horizon_key,
    head_thresholds,
)


@dataclass
class HorizonHeadSnapshot:
    horizon_key: str
    forward_bars: int
    horizon_minutes: int
    expected_return: float
    threshold: float
    short_threshold: float
    direction: str  # LONG, SHORT, FLAT
    confidence: float
    raw_long: bool
    raw_short: bool
    regime: str = "neutral"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_key": self.horizon_key,
            "forward_bars": self.forward_bars,
            "horizon_minutes": self.horizon_minutes,
            "expected_return": self.expected_return,
            "threshold": self.threshold,
            "short_threshold": self.short_threshold,
            "direction": self.direction,
            "confidence": self.confidence,
            "raw_long": self.raw_long,
            "raw_short": self.raw_short,
            "regime": self.regime,
        }


@dataclass
class MultiHorizonMLEvidence:
    heads: Dict[str, HorizonHeadSnapshot] = field(default_factory=dict)
    primary_execution_horizon_bars: int = 6
    alignment_score: float = 0.0
    opposition_detected: bool = False
    timing_head_key: str = "scalp_10m"
    execution_head_key: str = "intraday_30m"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "heads": {k: v.to_dict() for k, v in self.heads.items()},
            "primary_execution_horizon_bars": self.primary_execution_horizon_bars,
            "alignment_score": self.alignment_score,
            "opposition_detected": self.opposition_detected,
            "timing_head_key": self.timing_head_key,
            "execution_head_key": self.execution_head_key,
        }

    def head_for_bars(self, forward_bars: int) -> Optional[HorizonHeadSnapshot]:
        try:
            key = bars_to_horizon_key(forward_bars)
        except ValueError:
            return None
        return self.heads.get(key)


def _direction_from_return(
    expected_return: float,
    threshold: float,
    short_threshold: float,
    *,
    short_enabled: bool,
    eps: float,
) -> Tuple[str, bool, bool]:
    raw_long = bool(expected_return > (threshold - max(0.0, eps)))
    raw_short = bool(short_enabled and expected_return < -(short_threshold - max(0.0, eps)))
    if raw_long and not raw_short:
        return "LONG", raw_long, raw_short
    if raw_short and not raw_long:
        return "SHORT", raw_long, raw_short
    return "FLAT", raw_long, raw_short


def build_head_snapshot(
    *,
    horizon_key: str,
    forward_bars: int,
    expected_return: float,
    threshold: float,
    short_threshold: float,
    regime: str,
    short_enabled: bool,
    eps: float = 0.0,
) -> HorizonHeadSnapshot:
    direction, raw_long, raw_short = _direction_from_return(
        expected_return,
        threshold,
        short_threshold,
        short_enabled=short_enabled,
        eps=eps,
    )
    edge = abs(expected_return) - threshold
    conf = float(min(1.0, max(0.0, abs(edge) / 0.015 + 0.25)))
    return HorizonHeadSnapshot(
        horizon_key=horizon_key,
        forward_bars=int(forward_bars),
        horizon_minutes=forward_bars_to_minutes(forward_bars),
        expected_return=float(expected_return),
        threshold=float(threshold),
        short_threshold=float(short_threshold),
        direction=direction,
        confidence=conf,
        raw_long=raw_long,
        raw_short=raw_short,
        regime=str(regime or "neutral"),
    )


def build_multi_horizon_evidence(
    head_payloads: Mapping[str, Mapping[str, Any]],
    meta: Mapping[str, Any],
    *,
    short_enabled: bool = False,
    eps: float = 0.0,
) -> MultiHorizonMLEvidence:
    heads: Dict[str, HorizonHeadSnapshot] = {}
    for hkey in V43_HORIZON_KEYS:
        payload = head_payloads.get(hkey) or {}
        fb = int(payload.get("forward_bars", V43_HORIZON_KEY_TO_BARS[hkey]))
        thr, sthr = head_thresholds(meta, hkey)
        if payload.get("threshold") is not None:
            thr = float(payload["threshold"])
        if payload.get("short_threshold") is not None:
            sthr = abs(float(payload["short_threshold"]))
        heads[hkey] = build_head_snapshot(
            horizon_key=hkey,
            forward_bars=fb,
            expected_return=float(payload.get("expected_return", 0.0) or 0.0),
            threshold=thr,
            short_threshold=sthr,
            regime=str(payload.get("regime", "neutral") or "neutral"),
            short_enabled=short_enabled,
            eps=eps,
        )

    peh = int(meta.get("primary_execution_horizon_bars", 6) or 6)
    align = _compute_alignment(heads, peh)
    opp = _detect_opposition(heads, peh)
    return MultiHorizonMLEvidence(
        heads=heads,
        primary_execution_horizon_bars=peh,
        alignment_score=align,
        opposition_detected=opp,
    )


def _compute_alignment(heads: Dict[str, HorizonHeadSnapshot], thesis_bars: int) -> float:
    target = heads.get(bars_to_horizon_key(thesis_bars))
    if target is None or target.direction == "FLAT":
        return 0.0
    confirm_keys = V43_THESIS_CONFIRMATION_HEADS.get(thesis_bars, (thesis_bars,))
    agree = 0
    total = 0
    for fb in confirm_keys:
        try:
            key = bars_to_horizon_key(fb)
        except ValueError:
            continue
        h = heads.get(key)
        if h is None:
            continue
        total += 1
        if h.direction == target.direction:
            agree += 1
    return float(agree / total) if total else 0.0


def _detect_opposition(heads: Dict[str, HorizonHeadSnapshot], thesis_bars: int) -> bool:
    target = heads.get(bars_to_horizon_key(thesis_bars))
    if target is None or target.direction == "FLAT":
        return False
    opp_fb = V43_THESIS_OPPOSITION_HEADS.get(thesis_bars)
    if opp_fb is None:
        return False
    try:
        opp_key = bars_to_horizon_key(opp_fb)
    except ValueError:
        return False
    opp = heads.get(opp_key)
    if opp is None or opp.direction == "FLAT":
        return False
    return opp.direction != target.direction


def validate_thesis_against_multi_horizon(
    thesis_direction: str,
    thesis_horizon_bars: int,
    evidence: MultiHorizonMLEvidence,
) -> Tuple[bool, List[str]]:
    """Return (ok, reason_codes) for ml_and_thesis multi-head validation."""
    reasons: List[str] = []
    td = str(thesis_direction or "FLAT").upper()
    if td == "FLAT":
        return False, ["multi_horizon_thesis_flat"]
    if td not in ("LONG", "SHORT"):
        return False, ["multi_horizon_invalid_thesis_direction"]

    th_bars = int(thesis_horizon_bars or evidence.primary_execution_horizon_bars)
    target_head = evidence.head_for_bars(th_bars)
    if target_head is None:
        return False, [f"multi_horizon_missing_head_{th_bars}"]

    if target_head.direction != td:
        return False, [
            "multi_horizon_thesis_head_disagrees",
            f"thesis={td}",
            f"head_{target_head.horizon_key}={target_head.direction}",
        ]

    confirm = V43_THESIS_CONFIRMATION_HEADS.get(th_bars, (th_bars,))
    for fb in confirm:
        if fb == th_bars:
            continue
        try:
            key = bars_to_horizon_key(fb)
        except ValueError:
            continue
        h = evidence.heads.get(key)
        if h is None:
            reasons.append(f"multi_horizon_confirm_missing_{key}")
            continue
        if h.direction != td:
            return False, [
                "multi_horizon_confirm_head_disagrees",
                f"confirm_{key}={h.direction}",
                f"thesis={td}",
            ]

    if evidence.opposition_detected or _detect_opposition(evidence.heads, th_bars):
        opp_fb = V43_THESIS_OPPOSITION_HEADS.get(th_bars)
        if opp_fb is not None:
            try:
                opp_key = bars_to_horizon_key(opp_fb)
                opp_h = evidence.heads.get(opp_key)
                if opp_h and opp_h.direction not in ("FLAT", td):
                    return False, [
                        "multi_horizon_opposition_veto",
                        f"opp_{opp_key}={opp_h.direction}",
                    ]
            except ValueError:
                pass

    timing = evidence.heads.get(evidence.timing_head_key)
    if timing and timing.direction == "FLAT":
        return False, ["multi_horizon_timing_head_flat"]

    reasons.extend(
        [
            "multi_horizon_validation_passed",
            f"thesis_horizon_bars={th_bars}",
            f"alignment={evidence.alignment_score:.2f}",
        ]
    )
    return True, reasons


def primary_head_for_gates(evidence: MultiHorizonMLEvidence) -> HorizonHeadSnapshot:
    key = bars_to_horizon_key(evidence.primary_execution_horizon_bars)
    head = evidence.heads.get(key)
    if head is not None:
        return head
    return next(iter(evidence.heads.values()))
