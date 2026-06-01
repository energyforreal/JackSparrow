"""Setup quality score (0–1) from structural features only."""

from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.agent_thesis_engine import ThesisVerdict


def estimate_setup_quality(
    features: Dict[str, Any],
    thesis_verdict: "ThesisVerdict | None" = None,
) -> float:
    """Structural setup quality; thesis confidence is applied elsewhere in the pipeline."""
    _ = thesis_verdict
    adx = float(features.get("adx_14", 0.0) or 0.0)
    spread_bps = float(features.get("spread_bps", 99.0) or 99.0)
    squeeze = max(
        float(features.get("long_squeeze_risk", 0.0) or 0.0),
        float(features.get("short_squeeze_risk", 0.0) or 0.0),
    )
    spread_ok = spread_bps < 40
    squeeze_clear = squeeze < 0.3
    adx_score = min(1.0, adx / 40.0)
    quality = adx_score * 0.5 + (0.25 if spread_ok else 0.0) + (0.25 if squeeze_clear else 0.0)
    return float(max(0.0, min(1.0, quality)))
