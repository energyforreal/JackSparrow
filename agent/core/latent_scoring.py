"""Latent decision scoring (epsilon, kappa, q, A) — shadow and future policy integration."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

from agent.core.signal_vocabulary import is_long_signal, is_short_signal, normalize_signal


def _sigmoid(x: float) -> float:
    x = max(-20.0, min(20.0, float(x)))
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class LatentScoreResult:
    """Continuous ranking score S and optional shadow direction."""

    epsilon_proxy: float
    kappa: float
    q: float
    agreement: float
    score_s: float
    shadow_signal: str
    shadow_direction: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "epsilon_proxy": self.epsilon_proxy,
            "kappa": self.kappa,
            "q": self.q,
            "agreement": self.agreement,
            "score_s": self.score_s,
            "shadow_signal": self.shadow_signal,
            "shadow_direction": self.shadow_direction,
        }


def compute_latent_score(
    *,
    expected_return: float,
    threshold: float,
    kappa: float,
    trade_score: float,
    agreement: float,
    epsilon_scale: float = 0.005,
    policy_signal: Optional[str] = None,
) -> LatentScoreResult:
    """Compute S = sigmoid(eps/eps0) * kappa * q * A (shadow ranking)."""
    eps0 = max(float(epsilon_scale), 1e-6)
    epsilon_proxy = float(expected_return) - float(threshold)
    q = max(0.0, min(1.0, float(trade_score) / 100.0))
    k = max(0.0, min(1.0, float(kappa)))
    a = max(0.0, min(1.0, float(agreement)))
    s = _sigmoid(epsilon_proxy / eps0) * k * q * a

    direction: Optional[str] = None
    shadow = "HOLD"
    if epsilon_proxy > 0 and s >= 0.15:
        direction = "LONG"
        shadow = "LONG"
    elif epsilon_proxy < 0 and s >= 0.15:
        direction = "SHORT"
        shadow = "SHORT"

    pol = normalize_signal(policy_signal or "HOLD")
    if pol != "HOLD" and is_long_signal(pol):
        direction = "LONG"
    elif pol != "HOLD" and is_short_signal(pol):
        direction = "SHORT"

    return LatentScoreResult(
        epsilon_proxy=epsilon_proxy,
        kappa=k,
        q=q,
        agreement=a,
        score_s=s,
        shadow_signal=shadow,
        shadow_direction=direction,
    )
