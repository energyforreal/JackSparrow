"""Evidence graph: nodes (forecasts, structure) and support/contradict edges."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.core.evidence_types import EvidenceBundle, EvidenceDimension


@dataclass
class EvidenceNode:
    """Single evidence node in the decision graph."""

    node_id: str
    dimension: str
    score: float
    label: str
    source: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceEdge:
    """Directed edge between evidence nodes."""

    source_id: str
    target_id: str
    relation: str  # supports | contradicts | neutral
    weight: float = 1.0


@dataclass
class EvidenceGraph:
    """Serialized evidence graph for reasoning and DecisionReady telemetry."""

    nodes: List[EvidenceNode] = field(default_factory=list)
    edges: List[EvidenceEdge] = field(default_factory=list)
    summary: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "dimension": n.dimension,
                    "score": n.score,
                    "label": n.label,
                    "source": n.source,
                    "metadata": dict(n.metadata),
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "relation": e.relation,
                    "weight": e.weight,
                }
                for e in self.edges
            ],
            "summary": dict(self.summary),
        }


def build_evidence_graph(
    bundle: EvidenceBundle,
    *,
    direction: Optional[str] = None,
    market_forecast: Optional[Dict[str, Any]] = None,
    decision_context: Optional[Dict[str, Any]] = None,
) -> EvidenceGraph:
    """Build support/contradict graph from an EvidenceBundle."""
    nodes: List[EvidenceNode] = []
    edges: List[EvidenceEdge] = []
    dir_norm = str(direction or "HOLD").upper()
    is_long = dir_norm in ("LONG", "STRONG_LONG")
    is_short = dir_norm in ("SHORT", "STRONG_SHORT")

    for dim in EvidenceDimension:
        score = bundle.get(dim.value, 0.5)
        nodes.append(
            EvidenceNode(
                node_id=dim.value,
                dimension=dim.value,
                score=score,
                label=dim.value.replace("_", " ").title(),
                source="evidence_bundle",
            )
        )

    for extra_key, extra_score in bundle.scores.items():
        if extra_key in {d.value for d in EvidenceDimension}:
            continue
        nodes.append(
            EvidenceNode(
                node_id=extra_key,
                dimension=extra_key,
                score=float(extra_score),
                label=extra_key,
                source="evidence_bundle",
            )
        )

    if market_forecast and isinstance(market_forecast.get("regime_distribution"), dict):
        for regime, prob in market_forecast["regime_distribution"].items():
            nid = f"forecast_regime_{regime}"
            nodes.append(
                EvidenceNode(
                    node_id=nid,
                    dimension=EvidenceDimension.REGIME.value,
                    score=float(prob),
                    label=f"Regime {regime}",
                    source="market_forecast",
                )
            )

    trend_id = EvidenceDimension.TREND.value
    ml_id = EvidenceDimension.ML_EDGE.value
    if is_long:
        trend_score = bundle.get(trend_id, 0.5)
        ml_score = bundle.get(ml_id, 0.5)
        if trend_score >= 0.5:
            edges.append(EvidenceEdge(trend_id, ml_id, "supports", trend_score))
        else:
            edges.append(EvidenceEdge(trend_id, ml_id, "contradicts", 1.0 - trend_score))
        if ml_score < 0.4:
            edges.append(EvidenceEdge(ml_id, trend_id, "contradicts", 1.0 - ml_score))
    elif is_short:
        trend_score = bundle.get(trend_id, 0.5)
        inv_trend = 1.0 - trend_score
        if inv_trend >= 0.5:
            edges.append(EvidenceEdge(trend_id, ml_id, "supports", inv_trend))
        else:
            edges.append(EvidenceEdge(trend_id, ml_id, "contradicts", trend_score))

    liq = bundle.get(EvidenceDimension.LIQUIDITY.value, 0.5)
    struct = bundle.get(EvidenceDimension.STRUCTURE.value, 0.5)
    if liq >= 0.55 and struct >= 0.55:
        edges.append(
            EvidenceEdge(
                EvidenceDimension.LIQUIDITY.value,
                EvidenceDimension.STRUCTURE.value,
                "supports",
                min(liq, struct),
            )
        )
    elif liq < 0.4 or struct < 0.4:
        edges.append(
            EvidenceEdge(
                EvidenceDimension.LIQUIDITY.value,
                EvidenceDimension.STRUCTURE.value,
                "contradicts",
                max(1.0 - liq, 1.0 - struct),
            )
        )

    dc = decision_context if isinstance(decision_context, dict) else {}
    scenario = dc.get("scenario") if isinstance(dc.get("scenario"), dict) else {}
    expectation = dc.get("expectation") if isinstance(dc.get("expectation"), dict) else {}
    if scenario.get("primary"):
        sid = "scenario_primary"
        nodes.append(
            EvidenceNode(
                node_id=sid,
                dimension="scenario",
                score=float(scenario.get("confidence") or 0.5),
                label=str(scenario.get("primary")),
                source="cognition",
            )
        )
    if expectation.get("dominant_expectation"):
        eid = "expectation_dominant"
        nodes.append(
            EvidenceNode(
                node_id=eid,
                dimension="expectation",
                score=float(expectation.get("confidence") or 0.5),
                label=str(expectation.get("dominant_expectation")),
                source="cognition",
            )
        )
        if scenario.get("primary"):
            sp = str(scenario.get("primary"))
            de = str(expectation.get("dominant_expectation"))
            agree = (
                (sp in ("markup", "expansion") and de == "trend_continuation")
                or (sp == "compression" and de == "breakout")
            )
            edges.append(
                EvidenceEdge(
                    "scenario_primary",
                    eid,
                    "supports" if agree else "contradicts",
                    0.6,
                )
            )

    summary = dict(bundle.scores)
    return EvidenceGraph(nodes=nodes, edges=edges, summary=summary)
