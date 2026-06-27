"""O(1) rolling indicator state for incremental v43 feature append."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import pandas as pd


@dataclass
class V43IncrementalState:
    """Per-symbol rolling state for append-one-row feature updates."""

    symbol: str
    last_closed_timestamp: Optional[pd.Timestamp] = None
    row_count: int = 0
    indicator_cache: Dict[str, float] = field(default_factory=dict)

    def note_matrix(self, df_feat: pd.DataFrame) -> None:
        """Refresh state from a feature matrix tail."""
        if df_feat is None or len(df_feat) < 2:
            return
        self.row_count = len(df_feat)
        if "timestamp" in df_feat.columns:
            self.last_closed_timestamp = pd.Timestamp(df_feat["timestamp"].iloc[-2])
        closed = df_feat.iloc[-2]
        for col in df_feat.columns:
            if col == "timestamp":
                continue
            try:
                val = float(closed[col])
                if val == val:
                    self.indicator_cache[str(col)] = val
            except (TypeError, ValueError):
                continue

    def closed_features(self) -> Dict[str, float]:
        return dict(self.indicator_cache)


class V43IncrementalStateRegistry:
    """symbol -> incremental indicator state."""

    def __init__(self) -> None:
        self._states: Dict[str, V43IncrementalState] = {}

    def get(self, symbol: str) -> V43IncrementalState:
        sym = str(symbol or "").strip().upper()
        if sym not in self._states:
            self._states[sym] = V43IncrementalState(symbol=sym)
        return self._states[sym]

    def clear(self, symbol: Optional[str] = None) -> None:
        if symbol:
            self._states.pop(str(symbol).strip().upper(), None)
        else:
            self._states.clear()


v43_incremental_state_registry = V43IncrementalStateRegistry()
