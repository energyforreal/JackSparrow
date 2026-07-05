"""Enforce acyclic imports between cognition modules."""

from __future__ import annotations

import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_COGNITION = _REPO / "agent" / "intelligence" / "cognition"

_FORBIDDEN: dict[str, set[str]] = {
    "expectation_engine.py": {
        "strategy_selector",
        "strategy_scorer",
        "strategy_profiles",
        "hypothesis",
        "risk_intelligence",
    },
    "scenario_engine.py": {
        "strategy_selector",
        "strategy_scorer",
        "hypothesis",
    },
    "risk_intelligence.py": {
        "hypothesis",
        "strategy_selector",
        "strategy_scorer",
    },
    "strategy_selector.py": {
        "hypothesis",
        "agent_thesis_engine",
    },
}


def _imports_in_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_cognition_acyclic_import_constraints() -> None:
    for filename, forbidden in _FORBIDDEN.items():
        path = _COGNITION / filename
        assert path.exists(), f"missing {filename}"
        imports = _imports_in_file(path)
        for token in forbidden:
            assert token not in imports, f"{filename} must not import {token}"
