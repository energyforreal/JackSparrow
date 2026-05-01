"""Load labeled DataFrames for adaptive retrain (parquet source)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import structlog

logger = structlog.get_logger()


def load_labeled_parquet(parquet_dir: Path, timeframe: str) -> Optional[pd.DataFrame]:
    """Load ``labeled_{tf}.parquet`` if present."""
    if not parquet_dir or not str(parquet_dir).strip():
        return None
    p = Path(parquet_dir)
    if not p.is_dir():
        logger.debug(
            "adaptive_parquet_dir_missing",
            service="agent",
            component="labeled_data",
            path=str(p),
        )
        return None
    fp = p / f"labeled_{timeframe}.parquet"
    if not fp.is_file():
        logger.debug(
            "adaptive_parquet_file_missing",
            service="agent",
            component="labeled_data",
            path=str(fp),
        )
        return None
    try:
        return pd.read_parquet(fp)
    except Exception as e:
        logger.warning(
            "adaptive_parquet_read_failed",
            service="agent",
            component="labeled_data",
            path=str(fp),
            error=str(e),
        )
        return None
