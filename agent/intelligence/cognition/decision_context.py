"""Immutable DecisionContext and builder."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

from agent.intelligence.cognition.artifacts import ReasoningArtifact
from agent.intelligence.cognition.types import (
    CognitionMeta,
    ExpectationState,
    MarketMemory,
    MarketUnderstanding,
    RiskIntelligenceState,
    ScenarioState,
    StrategyScoreResult,
    StrategySelectionResult,
)


@dataclass(frozen=True)
class DecisionContext:
    """Immutable per-bar reasoning envelope."""

    meta: CognitionMeta
    understanding: Optional[MarketUnderstanding] = None
    memory: Optional[MarketMemory] = None
    scenario: Optional[ScenarioState] = None
    expectation: Optional[ExpectationState] = None
    risk_intelligence: Optional[RiskIntelligenceState] = None
    strategy_selection: Optional[StrategySelectionResult] = None
    strategy_scores: Optional[StrategyScoreResult] = None
    structural_evidence: Tuple[Tuple[str, float], ...] = ()
    behavioral_evidence: Tuple[Tuple[str, float], ...] = ()
    artifacts: Tuple[ReasoningArtifact, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "meta": self.meta.to_dict(),
            "structural_evidence": dict(self.structural_evidence),
            "behavioral_evidence": dict(self.behavioral_evidence),
            "artifacts": [a.to_dict() for a in self.artifacts],
        }
        if self.understanding is not None:
            out["understanding"] = self.understanding.to_dict()
        if self.memory is not None:
            out["memory"] = self.memory.to_dict()
        if self.scenario is not None:
            out["scenario"] = self.scenario.to_dict()
        if self.expectation is not None:
            out["expectation"] = self.expectation.to_dict()
        if self.risk_intelligence is not None:
            out["risk_intelligence"] = self.risk_intelligence.to_dict()
        if self.strategy_selection is not None:
            out["strategy_selection"] = self.strategy_selection.to_dict()
        if self.strategy_scores is not None:
            out["strategy_scores"] = self.strategy_scores.to_dict()
        return out

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "DecisionContext":
        meta_raw = raw.get("meta") or {}
        artifacts = tuple(
            ReasoningArtifact.from_dict(a)
            for a in (raw.get("artifacts") or [])
            if isinstance(a, dict)
        )
        struct = raw.get("structural_evidence") or {}
        behav = raw.get("behavioral_evidence") or {}
        return cls(
            meta=CognitionMeta(
                symbol=str(meta_raw.get("symbol") or ""),
                bar_index=int(meta_raw.get("bar_index") or 0),
                cycle_id=str(meta_raw.get("cycle_id") or ""),
                schema_version=str(meta_raw.get("schema_version") or "3.0"),
            ),
            understanding=(
                MarketUnderstanding.from_dict(raw["understanding"])
                if isinstance(raw.get("understanding"), dict)
                else None
            ),
            memory=(
                MarketMemory.from_dict(raw["memory"])
                if isinstance(raw.get("memory"), dict)
                else None
            ),
            scenario=(
                ScenarioState.from_dict(raw["scenario"])
                if isinstance(raw.get("scenario"), dict)
                else None
            ),
            expectation=(
                ExpectationState.from_dict(raw["expectation"])
                if isinstance(raw.get("expectation"), dict)
                else None
            ),
            risk_intelligence=(
                RiskIntelligenceState.from_dict(raw["risk_intelligence"])
                if isinstance(raw.get("risk_intelligence"), dict)
                else None
            ),
            strategy_selection=_selection_from_dict(raw.get("strategy_selection")),
            strategy_scores=_scores_from_dict(raw.get("strategy_scores")),
            structural_evidence=tuple(struct.items()) if isinstance(struct, dict) else (),
            behavioral_evidence=tuple(behav.items()) if isinstance(behav, dict) else (),
            artifacts=artifacts,
        )

    def to_legacy_market_context(self) -> Dict[str, Any]:
        """Backward-compatible keys for gradual migration."""
        out: Dict[str, Any] = {"decision_context_v3": self.to_dict()}
        if self.understanding is not None:
            out["market_state"] = self.understanding.to_dict()
        if self.expectation is not None:
            out["expectation"] = self.expectation.to_dict()
            out["market_forecast"] = self.expectation.to_dict()
        if self.scenario is not None:
            out["scenario"] = self.scenario.to_dict()
        if self.memory is not None:
            out["market_memory"] = self.memory.to_dict()
        if self.risk_intelligence is not None:
            out["risk_intelligence"] = self.risk_intelligence.to_dict()
        return out


def _selection_from_dict(raw: Any) -> Optional[StrategySelectionResult]:
    if not isinstance(raw, dict):
        return None
    from agent.intelligence.cognition.types import StrategySelectionEntry

    entries = tuple(
        StrategySelectionEntry(
            profile_id=str(e.get("profile_id") or ""),
            eligible=bool(e.get("eligible")),
            abstention_reason=e.get("abstention_reason"),
        )
        for e in (raw.get("entries") or [])
        if isinstance(e, dict)
    )
    return StrategySelectionResult(entries=entries)


def _scores_from_dict(raw: Any) -> Optional[StrategyScoreResult]:
    if not isinstance(raw, dict):
        return None
    from agent.intelligence.cognition.types import StrategyScoreEntry

    entries = []
    for e in raw.get("entries") or []:
        if not isinstance(e, dict):
            continue
        adj = e.get("adjustments") or {}
        entries.append(
            StrategyScoreEntry(
                profile_id=str(e.get("profile_id") or ""),
                base_confidence=float(e.get("base_confidence") or 0.0),
                adjustments=tuple(adj.items()) if isinstance(adj, dict) else (),
                adjusted_confidence=float(e.get("adjusted_confidence") or 0.0),
                agreement_with=tuple(str(a) for a in (e.get("agreement_with") or [])),
            )
        )
    return StrategyScoreResult(
        entries=tuple(entries),
        consensus_direction=str(raw.get("consensus_direction") or "FLAT"),
    )


@dataclass(frozen=True)
class CognitionInputs:
    """Read-only view of slices a module may consume."""

    understanding: Optional[MarketUnderstanding] = None
    memory: Optional[MarketMemory] = None
    scenario: Optional[ScenarioState] = None
    expectation: Optional[ExpectationState] = None
    risk_intelligence: Optional[RiskIntelligenceState] = None
    strategy_selection: Optional[StrategySelectionResult] = None
    features: Dict[str, Any] = field(default_factory=dict)
    structural_evidence: Dict[str, float] = field(default_factory=dict)
    behavioral_evidence: Dict[str, float] = field(default_factory=dict)
    portfolio_heat: float = 0.0
    daily_drawdown_pct: float = 0.0


@dataclass
class DecisionContextBuilder:
    """Assembles immutable DecisionContext; only builder mutates during cycle."""

    _meta: CognitionMeta = field(default_factory=CognitionMeta)
    _understanding: Optional[MarketUnderstanding] = None
    _memory: Optional[MarketMemory] = None
    _scenario: Optional[ScenarioState] = None
    _expectation: Optional[ExpectationState] = None
    _risk_intelligence: Optional[RiskIntelligenceState] = None
    _strategy_selection: Optional[StrategySelectionResult] = None
    _strategy_scores: Optional[StrategyScoreResult] = None
    _structural_evidence: Dict[str, float] = field(default_factory=dict)
    _behavioral_evidence: Dict[str, float] = field(default_factory=dict)
    _artifacts: List[ReasoningArtifact] = field(default_factory=list)

    def with_meta(self, meta: CognitionMeta) -> "DecisionContextBuilder":
        return replace(self, _meta=meta)

    def with_understanding(self, understanding: MarketUnderstanding) -> "DecisionContextBuilder":
        return replace(self, _understanding=understanding)

    def with_memory(self, memory: MarketMemory) -> "DecisionContextBuilder":
        return replace(self, _memory=memory)

    def with_scenario(self, scenario: ScenarioState) -> "DecisionContextBuilder":
        return replace(self, _scenario=scenario)

    def with_expectation(self, expectation: ExpectationState) -> "DecisionContextBuilder":
        return replace(self, _expectation=expectation)

    def with_risk_intelligence(self, risk: RiskIntelligenceState) -> "DecisionContextBuilder":
        return replace(self, _risk_intelligence=risk)

    def with_strategy_selection(self, selection: StrategySelectionResult) -> "DecisionContextBuilder":
        return replace(self, _strategy_selection=selection)

    def with_strategy_scores(self, scores: StrategyScoreResult) -> "DecisionContextBuilder":
        return replace(self, _strategy_scores=scores)

    def with_structural_evidence(self, evidence: Dict[str, float]) -> "DecisionContextBuilder":
        return replace(self, _structural_evidence=dict(evidence))

    def with_behavioral_evidence(self, evidence: Dict[str, float]) -> "DecisionContextBuilder":
        return replace(self, _behavioral_evidence=dict(evidence))

    def append_artifact(self, artifact: ReasoningArtifact) -> "DecisionContextBuilder":
        arts = list(self._artifacts)
        arts.append(artifact)
        return replace(self, _artifacts=arts)

    def build(self) -> DecisionContext:
        return DecisionContext(
            meta=self._meta,
            understanding=self._understanding,
            memory=self._memory,
            scenario=self._scenario,
            expectation=self._expectation,
            risk_intelligence=self._risk_intelligence,
            strategy_selection=self._strategy_selection,
            strategy_scores=self._strategy_scores,
            structural_evidence=tuple(self._structural_evidence.items()),
            behavioral_evidence=tuple(self._behavioral_evidence.items()),
            artifacts=tuple(self._artifacts),
        )

    def to_inputs(
        self,
        *,
        features: Optional[Dict[str, Any]] = None,
        portfolio_heat: float = 0.0,
        daily_drawdown_pct: float = 0.0,
    ) -> CognitionInputs:
        return CognitionInputs(
            understanding=self._understanding,
            memory=self._memory,
            scenario=self._scenario,
            expectation=self._expectation,
            risk_intelligence=self._risk_intelligence,
            strategy_selection=self._strategy_selection,
            features=dict(features or {}),
            structural_evidence=dict(self._structural_evidence),
            behavioral_evidence=dict(self._behavioral_evidence),
            portfolio_heat=portfolio_heat,
            daily_drawdown_pct=daily_drawdown_pct,
        )
