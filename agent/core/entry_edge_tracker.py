"""Rolling history of entry |buy-sell| strength for optional percentile gating."""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np


class EntryEdgeTracker:
    """Per-symbol deque of recent edge strengths (absolute buy-sell gap on entry TF)."""

    max_len: int = 256
    _edges: Dict[str, deque] = {}

    @classmethod
    def clear_for_tests(cls) -> None:
        """Reset state (unit tests only)."""
        cls._edges.clear()

    @classmethod
    def observe(cls, symbol: str, strength: float) -> None:
        """Append this bar's strength after decisions (strength >= 0)."""
        if not symbol:
            return
        if symbol not in cls._edges:
            cls._edges[symbol] = deque(maxlen=cls.max_len)
        cls._edges[symbol].append(float(strength))

    @classmethod
    def strength_vs_prior_percentile(
        cls,
        symbol: str,
        strength: float,
        percentile: int,
        min_samples: int,
    ) -> Tuple[bool, Optional[float]]:
        """
        True if strength should pass the gate (>= historical percentile or short history).

        Uses prior samples only (current bar not yet in deque).
        """
        if not symbol or min_samples <= 0:
            return True, None
        hist: List[float] = list(cls._edges.get(symbol) or [])
        if len(hist) < min_samples:
            return True, None
        thr = float(np.percentile(hist, percentile))
        return bool(strength >= thr), thr
