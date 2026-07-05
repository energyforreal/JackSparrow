"""Reasoning artifacts for replay and telemetry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class ReasoningArtifact:
    """One module's inputs, output, and timing for a single bar cycle."""

    module_id: str
    confidence: float = 0.0
    reason_codes: Tuple[str, ...] = ()
    inputs: Dict[str, Any] = field(default_factory=dict)
    output: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_id": self.module_id,
            "confidence": float(self.confidence),
            "reason_codes": list(self.reason_codes),
            "inputs": dict(self.inputs),
            "output": dict(self.output),
            "duration_ms": float(self.duration_ms),
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ReasoningArtifact":
        return cls(
            module_id=str(raw.get("module_id") or ""),
            confidence=float(raw.get("confidence") or 0.0),
            reason_codes=tuple(str(c) for c in (raw.get("reason_codes") or [])),
            inputs=dict(raw.get("inputs") or {}),
            output=dict(raw.get("output") or {}),
            duration_ms=float(raw.get("duration_ms") or 0.0),
        )
