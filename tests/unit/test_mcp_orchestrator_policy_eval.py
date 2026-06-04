"""Regression: v43 prediction path must evaluate policy once (BUG-03)."""

from __future__ import annotations

import ast
from pathlib import Path


def _count_policy_evaluate_calls_in_v43_handler() -> int:
    root = Path(__file__).resolve().parents[2]
    source = (root / "agent" / "core" / "mcp_orchestrator.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    target_name = "_process_jacksparrow_v43_prediction"
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or node.name != target_name:
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            func = child.func
            if isinstance(func, ast.Attribute) and func.attr == "evaluate":
                base = func.value
                if isinstance(base, ast.Name) and base.id == "agent_policy_engine":
                    count += 1
                elif isinstance(base, ast.Attribute) and base.attr == "agent_policy_engine":
                    count += 1
        break
    else:
        raise AssertionError(f"{target_name} not found in mcp_orchestrator.py")
    return count


def test_v43_handler_calls_policy_evaluate_once() -> None:
    assert _count_policy_evaluate_calls_in_v43_handler() == 1
