"""Generated swinging notebooks stay on the Colab local disk."""

from __future__ import annotations

from pathlib import Path

NOTEBOOKS = (
    "01_delta_historical_data.ipynb",
    "02_feature_engineering.ipynb",
    "03_algorithmic_setup_generation.ipynb",
    "04_trade_outcome_engine.ipynb",
    "05_setup_effectiveness_training.ipynb",
    "06_sr_effectiveness_training.ipynb",
    "07_walk_forward_backtesting.ipynb",
    "08_model_export.ipynb",
)


def test_notebooks_do_not_mount_drive() -> None:
    folder = Path(__file__).resolve().parents[2] / "scripts" / "colab"
    for name in NOTEBOOKS:
        text = (folder / name).read_text(encoding="utf-8").lower()
        assert "drive.mount" not in text
        assert "google.colab.drive" not in text
        assert "googleapiclient" not in text
        assert "/content/jacksparrow" in text
        assert "api.india.delta.exchange" in text or "collect_all" in text or "materialize_" in text
