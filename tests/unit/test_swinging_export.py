"""Research export and runtime nodes cannot enable orders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.models.mcp_model_node import MCPModelRequest
from agent.models.setup_effectiveness_node import SetupEffectivenessNode
from agent.models.sr_effectiveness_node import SREffectivenessNode
from agent.models.swinging_bundle import load_research_bundle
from research.forecast_30m import pipeline_v5
from research.swinging.contract import SETUP_BUNDLE_DIR
from research.swinging.export_bundle import export_download_zip, write_research_bundle
from research.swinging.models import fit_bundle


def _artifact() -> dict:
    pytest.importorskip("xgboost")
    pytest.importorskip("lightgbm")
    import numpy as np
    import pandas as pd

    rows = 36
    labels = np.array(["win", "loss", "other"] * rows)[:rows]
    frame = pd.DataFrame(
        {
            "f1": np.linspace(0.0, 1.0, rows),
            "f2": np.linspace(1.0, 0.0, rows),
            "outcome_class": labels,
        }
    )
    return fit_bundle(frame, ["f1", "f2"], target="outcome_class", positive_class="win", n_trials=0)


def test_bundle_is_research_only_and_checksum_matches(tmp_path: Path) -> None:
    artifact = _artifact()
    bundle = write_research_bundle(
        tmp_path / SETUP_BUNDLE_DIR,
        artifact,
        task="setup_effectiveness",
        metrics={"validation": {"net_expectancy": 0.0}, "test": {"trades": 0}},
        dataset_version="unit",
        training_period={"earliest": "2024-01-01", "latest": "2024-02-01"},
    )
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["orders_enabled"] is False
    assert manifest["promotion_status"] == "research"
    node = SetupEffectivenessNode(bundle, load_research_bundle(bundle))
    import asyncio

    asyncio.run(node.initialize())
    prediction = asyncio.run(
        node.predict(MCPModelRequest(features=[], context={"features": {"f1": 0.2, "f2": 0.4}}))
    )
    assert prediction.context["orders_enabled"] is False
    assert prediction.context["contributes_to_consensus"] is False
    manifest["orders_enabled"] = True
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="cannot enable orders"):
        SetupEffectivenessNode.from_model_dir(tmp_path)


def test_sr_node_refuses_a_non_research_manifest(tmp_path: Path) -> None:
    artifact = _artifact()
    artifact["positive_class"] = None
    bundle = write_research_bundle(
        tmp_path / "JackSparrow_SREffectiveness_BTCUSD",
        artifact,
        task="sr_effectiveness",
        metrics={},
        dataset_version="unit",
        training_period={"earliest": "", "latest": ""},
    )
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["promotion_status"] = "live"
    (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="research-only"):
        SREffectivenessNode.from_model_dir(tmp_path)


def test_export_zip_stays_out_of_model_storage(tmp_path: Path) -> None:
    artifact = _artifact()
    experiment = tmp_path / "experiments" / "setup_effectiveness"
    experiment.mkdir(parents=True)
    import joblib

    joblib.dump(artifact, experiment / "models.joblib")
    zip_path = export_download_zip(tmp_path, task="setup_effectiveness")
    assert zip_path.endswith("setup_effectiveness.zip")
    assert "model_storage" not in zip_path
    with pytest.raises(RuntimeError, match="model storage"):
        write_research_bundle(
            tmp_path / "model_storage" / "bundle",
            artifact,
            task="setup_effectiveness",
            metrics={},
            dataset_version="unit",
            training_period={"earliest": "", "latest": ""},
        )


def test_promote_refuses_override_and_strips_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "models.joblib").write_bytes(b"model")
    (blocked / "manifest.json").write_text(
        json.dumps(
            {
                "development_gate_passed": True,
                "promotion_override": "force_promote_live_floor_0.55",
                "orders_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    assert pipeline_v5._maybe_promote(blocked, True) is False
    destination = tmp_path / "agent_bundle"
    monkeypatch.setattr(pipeline_v5, "_AGENT_BUNDLE", destination)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "models.joblib").write_bytes(b"model")
    (allowed / "manifest.json").write_text(
        json.dumps({"development_gate_passed": True, "orders_enabled": True}),
        encoding="utf-8",
    )
    assert pipeline_v5._maybe_promote(allowed, True) is True
    written = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert "promotion_override" not in written
    assert written["promoted_to_agent"] is True
