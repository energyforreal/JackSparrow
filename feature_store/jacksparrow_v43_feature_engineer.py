"""JackSparrow v43 feature engineer for training export and optional local parity checks.

Pickled instances should expose ``transform(df_5m, df_15m, df_1h, df_funding,
include_target=...)`` matching the contract used by
:class:`agent.models.jack_sparrow_v43_node.JackSparrowV43Node` inference.

Implementation delegates feature columns to :func:`build_v43_feature_matrix`
in :mod:`feature_store.jacksparrow_v43_build_matrix` (same semantics as
:mod:`feature_store.jacksparrow_v43_mcp_row` / v43 contract tests).
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd

from feature_store.jacksparrow_v43_build_matrix import build_v43_feature_matrix
from feature_store.jacksparrow_v43_contract import (
    V43_CANONICAL_FEATURES,
    V43_FORWARD_TARGET_BARS,
)
from feature_store.jacksparrow_v43_mcp_row import _ohlc


class JackSparrowV43FeatureEngineer:
    """Vectorized v43 features + optional forward-return target for training."""

    def __init__(self, feature_names: Optional[List[str]] = None) -> None:
        names = list(feature_names) if feature_names is not None else list(V43_CANONICAL_FEATURES)
        self.columns: List[str] = names

    def transform(
        self,
        df_5m: pd.DataFrame,
        df_15m: pd.DataFrame,
        df_1h: Optional[pd.DataFrame] = None,
        df_funding: Optional[pd.DataFrame] = None,
        include_target: bool = False,
    ) -> pd.DataFrame:
        """Return feature matrix aligned to ``df_5m`` rows.

        When ``include_target`` is True, appends ``target`` column: simple forward
        return ``close[t + H] / close[t] - 1`` with ``H`` = :data:`V43_FORWARD_TARGET_BARS`
        on 5m closes (NaN on tail rows without future).
        """
        out = build_v43_feature_matrix(
            df_5m,
            df_15m,
            df_1h,
            df_funding,
            for_training=include_target,
            primary_interval="5m",
        )
        if out.empty or not self.columns:
            return out

        missing = [c for c in self.columns if c not in out.columns]
        if missing:
            raise ValueError(
                "JackSparrowV43FeatureEngineer: build_v43_feature_matrix output "
                f"missing columns: {missing[:12]}"
                + (" …" if len(missing) > 12 else "")
            )

        keep = list(self.columns)
        for extra in ("timestamp", "regime_label"):
            if extra in out.columns and extra not in keep:
                keep.append(extra)

        result = out[keep].copy()

        if include_target:
            d = _ohlc(df_5m)
            if len(d) != len(result):
                raise ValueError(
                    "JackSparrowV43FeatureEngineer: primary OHLC length mismatch "
                    f"after transform ({len(d)} vs {len(result)})"
                )
            c = d["close"].astype(float)
            horizon = int(V43_FORWARD_TARGET_BARS)
            fwd = c.shift(-horizon) / c - 1.0
            result = result.copy()
            tgt = pd.Series(fwd.values, dtype="float64").replace([np.inf, -np.inf], np.nan)
            result["target"] = tgt

        return result
