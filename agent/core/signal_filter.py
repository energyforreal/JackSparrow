"""
Post-consensus entry filters: trade frequency cap and breakout score gate.

Frequency cap counts only trades that passed all other checks (call record_trade after publish).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Mapping, Optional, Tuple


class EntrySignalFilter:
    """Rolling max trades/hour and optional breakout score floor for BUY."""

    def __init__(
        self,
        max_trades_per_hour: int = 0,
        min_breakout_score: float = 0.0,
    ) -> None:
        self.max_trades_per_hour = max(0, int(max_trades_per_hour))
        self.min_breakout_score = float(min_breakout_score)
        self._trade_timestamps: List[datetime] = []

    def _prune(self, now: datetime) -> None:
        if self.max_trades_per_hour <= 0:
            return
        cutoff = now - timedelta(hours=1)
        self._trade_timestamps = [t for t in self._trade_timestamps if t > cutoff]

    def apply(
        self,
        signal: str,
        features: Mapping[str, Any],
        *,
        now: Optional[datetime] = None,
    ) -> Tuple[str, str]:
        """
        Returns (signal, reason). Does not record a trade — call record_trade() after RiskApproved.
        """
        if signal == "HOLD" or signal not in (
            "BUY",
            "STRONG_BUY",
            "SELL",
            "STRONG_SELL",
        ):
            return signal, "not an entry signal"

        ts = now or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        self._prune(ts)

        if self.max_trades_per_hour > 0 and len(self._trade_timestamps) >= self.max_trades_per_hour:
            return "HOLD", f"max_trades_per_hour={self.max_trades_per_hour}"

        if signal in ("BUY", "STRONG_BUY") and self.min_breakout_score > 0:
            raw = features.get("bo_breakout_score")
            if raw is not None:
                try:
                    bo = float(raw)
                    if bo < self.min_breakout_score:
                        return (
                            "HOLD",
                            f"bo_breakout_score {bo:.3f} < {self.min_breakout_score}",
                        )
                except (TypeError, ValueError):
                    pass

        return signal, "passed entry_signal_filter"

    def record_trade(self, when: Optional[datetime] = None) -> None:
        """Call after RiskApprovedEvent is published so the cap reflects real sends."""
        if self.max_trades_per_hour <= 0:
            return
        ts = when or datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        self._trade_timestamps.append(ts)
