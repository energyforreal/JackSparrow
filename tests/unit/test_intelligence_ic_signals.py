"""IC signal shaping: direction magnitude and MTF alignment."""

from __future__ import annotations

from agent.core.agent_thesis_engine import ThesisVerdict
from agent.intelligence.direction_signal import compute_direction_signal
from agent.intelligence.mtf_synthesizer import compute_mtf_alignment
from agent.intelligence.setup_quality import estimate_setup_quality
from agent.intelligence.vol_estimator import estimate_vol_expansion


def test_direction_signal_confidence_floor() -> None:
    thesis = ThesisVerdict(signal="BUY", confidence=0.62, position_size=0.0)
    er = compute_direction_signal(thesis)
    assert er == 0.012 * 0.62
    weak = ThesisVerdict(signal="BUY", confidence=0.3, position_size=0.0)
    assert compute_direction_signal(weak) == 0.012 * 0.5


def test_mtf_alignment_conflict_vs_hold() -> None:
    buy = ThesisVerdict(signal="BUY", confidence=0.7, position_size=0.0)
    sell = ThesisVerdict(signal="SELL", confidence=0.7, position_size=0.0)
    hold = ThesisVerdict(signal="HOLD", confidence=0.0, position_size=0.0)

    assert compute_mtf_alignment(buy, buy, buy) == 1.0
    assert compute_mtf_alignment(buy, buy, hold) == 0.6
    assert compute_mtf_alignment(buy, buy, sell) == 0.2
    assert compute_mtf_alignment(hold, hold, hold) == 0.0


def test_setup_quality_structural_only() -> None:
    feats = {"adx_14": 30.0, "spread_bps": 20.0, "long_squeeze_risk": 0.1}
    q_high = estimate_setup_quality(feats, ThesisVerdict(signal="HOLD", confidence=0.1, position_size=0.0))
    q_low_conf = estimate_setup_quality(feats, ThesisVerdict(signal="BUY", confidence=0.9, position_size=0.0))
    assert q_high == q_low_conf
    assert q_high > 0.5


def test_vol_estimator_real_atr_ratio_not_inflated() -> None:
    score_true_one = estimate_vol_expansion({"atr_pct": 0.01, "vol_regime": 1.0, "atr_ratio_14_50": 1.0})
    score_missing = estimate_vol_expansion({"atr_pct": 0.01, "vol_regime": 1.0})
    assert score_true_one < score_missing
