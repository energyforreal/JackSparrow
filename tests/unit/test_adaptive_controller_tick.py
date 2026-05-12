"""Adaptive controller orchestration smoke tests."""

import pytest


@pytest.mark.asyncio
async def test_run_adaptive_retrain_tick_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent.core import config

    monkeypatch.setattr(config.settings, "adaptive_retrain_enabled", False, raising=False)
    from agent.learning.adaptive.adaptive_controller import run_adaptive_retrain_tick

    out = await run_adaptive_retrain_tick(None)
    assert out.get("ran") is False
    assert out.get("reason") == "disabled"


@pytest.mark.asyncio
async def test_run_adaptive_retrain_tick_none_source(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from agent.core import config

    legacy_bundle = tmp_path / "legacy_no_v43"
    legacy_bundle.mkdir()
    monkeypatch.setattr(config.settings, "adaptive_retrain_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "model_dir", str(legacy_bundle), raising=False)
    monkeypatch.setattr(
        config.settings, "adaptive_labeled_data_source", "none", raising=False
    )
    from agent.learning.adaptive.adaptive_controller import run_adaptive_retrain_tick

    out = await run_adaptive_retrain_tick(None)
    assert out.get("ran") is False
    assert "none" in str(out.get("reason", ""))


@pytest.mark.asyncio
async def test_run_adaptive_retrain_tick_skips_v43_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from agent.core import config

    bundle = tmp_path / "v43bundle"
    bundle.mkdir()
    (bundle / "metadata_v43.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(config.settings, "adaptive_retrain_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "model_dir", str(bundle), raising=False)
    monkeypatch.setattr(
        config.settings, "adaptive_labeled_data_source", "parquet", raising=False
    )
    from agent.learning.adaptive.adaptive_controller import run_adaptive_retrain_tick

    out = await run_adaptive_retrain_tick(None)
    assert out.get("ran") is False
    assert out.get("reason") == "jacksparrow_v43_model_dir"


@pytest.mark.asyncio
async def test_run_adaptive_retrain_tick_skips_v44_named_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from agent.core import config

    bundle = tmp_path / "v44bundle"
    bundle.mkdir()
    (bundle / "metadata_v44.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(config.settings, "adaptive_retrain_enabled", True, raising=False)
    monkeypatch.setattr(config.settings, "model_dir", str(bundle), raising=False)
    monkeypatch.setattr(
        config.settings, "adaptive_labeled_data_source", "parquet", raising=False
    )
    from agent.learning.adaptive.adaptive_controller import run_adaptive_retrain_tick

    out = await run_adaptive_retrain_tick(None)
    assert out.get("ran") is False
    assert out.get("reason") == "jacksparrow_v43_model_dir"
