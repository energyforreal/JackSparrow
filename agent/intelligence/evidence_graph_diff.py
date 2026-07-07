"""Compare entry-time vs live evidence graph for position invalidation hints."""

from __future__ import annotations

from typing import Any, Dict, List, Set


def _node_keys(graph: Dict[str, Any]) -> Set[str]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return set()
    keys: Set[str] = set()
    for n in nodes:
        if isinstance(n, dict):
            nid = n.get("id") or n.get("key")
            if nid:
                keys.add(str(nid))
    return keys


def diff_evidence_graphs(
    entry_graph: Dict[str, Any],
    live_graph: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Diff entry vs live evidence graphs.

    Returns invalidation hints for Trade Lifecycle health scoring.
    """
    entry_keys = _node_keys(entry_graph)
    live_keys = _node_keys(live_graph)
    lost = sorted(entry_keys - live_keys)
    gained = sorted(live_keys - entry_keys)

    invalidations: List[str] = []
    if lost:
        invalidations.append(f"evidence_nodes_lost:{len(lost)}")
    entry_forecast = str(entry_graph.get("forecast_direction") or "").lower()
    live_forecast = str(live_graph.get("forecast_direction") or "").lower()
    if entry_forecast and live_forecast and entry_forecast != live_forecast:
        invalidations.append(f"forecast_flip:{entry_forecast}->{live_forecast}")

    alignment = 1.0
    if entry_keys:
        overlap = len(entry_keys & live_keys) / max(len(entry_keys), 1)
        alignment = overlap
        if overlap < 0.5:
            invalidations.append("evidence_graph_diverged")

    return {
        "alignment": round(alignment, 4),
        "nodes_lost": lost[:20],
        "nodes_gained": gained[:20],
        "invalidation_codes": invalidations,
    }


def graph_diff_from_snapshots(
    entry_snapshot: Dict[str, Any],
    live_mc: Dict[str, Any],
) -> Dict[str, Any]:
    """Extract graphs from entry snapshot and live market context."""
    entry_dc = entry_snapshot.get("decision_context")
    entry_graph: Dict[str, Any] = {}
    if isinstance(entry_dc, dict):
        eg = entry_dc.get("evidence_graph")
        if isinstance(eg, dict):
            entry_graph = eg
    live_graph = live_mc.get("evidence_graph")
    if not isinstance(live_graph, dict):
        live_graph = {}
    if not entry_graph:
        return {"alignment": 1.0, "invalidation_codes": [], "nodes_lost": [], "nodes_gained": []}
    return diff_evidence_graphs(entry_graph, live_graph)
