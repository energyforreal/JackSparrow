"""Tests for JackSparrow v43 node context helpers (no ambiguous DataFrame boolean checks)."""

from __future__ import annotations

import pandas as pd
import pytest

from agent.models.jack_sparrow_v43_node import _ctx_dataframe


def test_ctx_dataframe_primary_df_without_boolean_eval() -> None:
    df = pd.DataFrame({"a": [1]})
    ctx = {"v43_df5m": df}
    assert _ctx_dataframe(ctx, "v43_df5m", "df5m") is df


def test_ctx_dataframe_fallback_when_primary_missing() -> None:
    df = pd.DataFrame({"b": [2]})
    ctx = {"df5m": df}
    assert _ctx_dataframe(ctx, "v43_df5m", "df5m") is df


def test_ctx_dataframe_primary_non_df_falls_back_to_df() -> None:
    df = pd.DataFrame({"c": [3]})
    ctx = {"v43_df5m": "not-a-frame", "df5m": df}
    assert _ctx_dataframe(ctx, "v43_df5m", "df5m") is df


def test_ctx_dataframe_returns_none_when_missing() -> None:
    assert _ctx_dataframe({}, "v43_df5m", "df5m") is None


def test_ctx_dataframe_primary_df_never_triggers_ambiguous_truth_error() -> None:
    """``_ctx_dataframe`` must work when primary key holds a DataFrame (``or`` chaining does not)."""
    df_primary = pd.DataFrame({"x": [1]})
    df_fallback = pd.DataFrame({"y": [2]})
    ctx = {"v43_df5m": df_primary, "df5m": df_fallback}
    # Must not raise
    out = _ctx_dataframe(ctx, "v43_df5m", "df5m")
    assert out is df_primary


def test_boolean_or_on_nonempty_dataframe_is_ambiguous_documentation() -> None:
    """Regression: ``df_primary or df_fallback`` truth-tests the left DataFrame."""
    df_primary = pd.DataFrame({"z": [1]})
    df_fallback = pd.DataFrame({"w": [2]})
    ctx = {"v43_df5m": df_primary, "df5m": df_fallback}
    with pytest.raises(ValueError, match="truth value of a DataFrame is ambiguous"):
        _ = ctx.get("v43_df5m") or ctx.get("df5m")
