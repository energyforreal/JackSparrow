"""Unit tests for evidence graph diff."""

from agent.intelligence.evidence_graph_diff import diff_evidence_graphs


def test_graph_diff_detects_lost_nodes() -> None:
    entry = {"nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
    live = {"nodes": [{"id": "a"}]}
    result = diff_evidence_graphs(entry, live)
    assert result["alignment"] < 0.5
    assert "evidence_graph_diverged" in result["invalidation_codes"]
    assert "b" in result["nodes_lost"]
