"""Unit tests for train_transformer_resolution CLI helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from feature_store.transformer_btcusd.contract import SUPPORTED_RESOLUTIONS, bundle_dir_name
from scripts.colab.train_transformer_resolution import run_all_training


@patch("scripts.colab.train_transformer_resolution.run_training")
def test_run_all_training_iterates_all_resolutions(mock_run_training) -> None:
    export_dir = Path("export")

    results = run_all_training(export_dir=export_dir)

    assert len(results) == len(SUPPORTED_RESOLUTIONS)
    assert mock_run_training.call_count == len(SUPPORTED_RESOLUTIONS)
    for resolution, result in zip(SUPPORTED_RESOLUTIONS, results):
        assert result["resolution"] == resolution
        assert result["status"] == "ok"
        assert result["error"] is None
        assert result["export_dir"] == str(export_dir / bundle_dir_name(resolution))


@patch("scripts.colab.train_transformer_resolution.run_training")
def test_run_all_training_uses_per_tf_export_subdirs(mock_run_training) -> None:
    export_dir = Path("/content/export")

    run_all_training(resolutions=["15m", "1h"], export_dir=export_dir)

    calls = mock_run_training.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs["resolution"] == "15m"
    assert calls[0].kwargs["export_dir"] == export_dir / "JackSparrow_Transformer_BTCUSD_15m"
    assert calls[0].kwargs["raw_cache_path"] == Path("btcusd_15m_raw.parquet")
    assert calls[1].kwargs["resolution"] == "1h"
    assert calls[1].kwargs["export_dir"] == export_dir / "JackSparrow_Transformer_BTCUSD_1h"


@patch("scripts.colab.train_transformer_resolution.run_training")
def test_run_all_training_continue_on_error(mock_run_training) -> None:
    mock_run_training.side_effect = [None, RuntimeError("quality gate failed"), None]

    results = run_all_training(
        resolutions=["5m", "15m", "30m"],
        export_dir=Path("export"),
        continue_on_error=True,
    )

    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "failed"
    assert "quality gate failed" in results[1]["error"]
    assert results[2]["status"] == "ok"
    assert mock_run_training.call_count == 3


@patch("scripts.colab.train_transformer_resolution.run_training")
def test_run_all_training_raises_on_error_by_default(mock_run_training) -> None:
    mock_run_training.side_effect = RuntimeError("quality gate failed")

    with pytest.raises(RuntimeError, match="quality gate failed"):
        run_all_training(
            resolutions=["15m"],
            export_dir=Path("export"),
            continue_on_error=False,
        )
