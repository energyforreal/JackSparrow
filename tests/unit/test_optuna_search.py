"""Tests for fused-model Optuna search (val CE only, never test)."""

from __future__ import annotations

import json
import sys
import types
from typing import Any, Dict

import numpy as np
import torch

from scripts.colab.mtf_fusion_model import MtfFusionTransformer
from scripts.colab.mtf_fusion_research import optuna_cache_identity, optuna_search


class _FakeTrial:
    number = 0

    def suggest_float(self, name: str, low: float, high: float, log: bool = False) -> float:
        values = {"lr": 2e-4, "weight_decay": 2e-3, "dropout": 0.28}
        return float(values[name])


class _FakeFrozenTrial:
    def __init__(self, params: Dict[str, float], value: float) -> None:
        self.params = params
        self.value = value
        self.number = 0


class _FakeStudy:
    def __init__(self) -> None:
        self.optimize_calls = 0
        self.best_params = {"lr": 2e-4, "weight_decay": 2e-3, "dropout": 0.28}
        self.best_value = 0.61
        self.trials: list[_FakeFrozenTrial] = []

    def optimize(self, fn: Any, n_trials: int, catch: Any = ()) -> None:
        self.optimize_calls += 1
        value = fn(_FakeTrial())
        self.trials.append(_FakeFrozenTrial(dict(self.best_params), float(value)))


def _install_fake_optuna(monkeypatch: Any, study: _FakeStudy) -> None:
    fake = types.ModuleType("optuna")

    def create_study(*, direction: str) -> _FakeStudy:
        assert direction == "minimize"
        return study

    fake.create_study = create_study  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "optuna", fake)


def test_optuna_skipped_does_not_optimize(monkeypatch: Any) -> None:
    study = _FakeStudy()
    _install_fake_optuna(monkeypatch, study)
    cfg = {"run_optuna": False, "lr": 1e-4, "dropout": 0.3, "weight_decay": 1e-3}
    out = optuna_search(
        cfg,
        n_features=4,
        train_loader=object(),  # type: ignore[arg-type]
        val_loader=object(),  # type: ignore[arg-type]
        device=torch.device("cpu"),
        train_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no train")),
    )
    assert study.optimize_calls == 0
    assert out["lr"] == 1e-4
    assert "optuna_best" not in out


def test_optuna_writes_best_params(monkeypatch: Any) -> None:
    study = _FakeStudy()
    _install_fake_optuna(monkeypatch, study)
    trained = {"n": 0}

    def fake_train(
        model: MtfFusionTransformer,
        train_loader: object,
        val_loader: object,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        trained["n"] += 1
        assert kwargs["lr"] == 2e-4
        return {"ok": True, "best_val_loss": 0.61, "history": [(1, 0.7, 0.61)]}

    def fake_factory(n_features: int, config: Dict[str, Any]) -> MtfFusionTransformer:
        return MtfFusionTransformer(
            n_features=n_features, d_model=16, nhead=2, num_layers=1, max_len=8
        )

    cfg = {
        "run_optuna": True,
        "optuna_trials": 3,
        "optuna_trial_epochs": 2,
        "lr": 1e-4,
        "dropout": 0.3,
        "weight_decay": 1e-3,
        "label_smoothing": 0.05,
        "horizon_loss_weights": [1.0, 0.8, 0.4],
        "lr_schedule": "cosine",
    }
    out = optuna_search(
        cfg,
        n_features=4,
        train_loader=object(),  # type: ignore[arg-type]
        val_loader=object(),  # type: ignore[arg-type]
        device=torch.device("cpu"),
        train_fn=fake_train,
        model_factory=fake_factory,
    )
    assert study.optimize_calls == 1
    assert trained["n"] == 1
    assert out["lr"] == 2e-4
    assert out["dropout"] == 0.28
    assert out["weight_decay"] == 2e-3
    assert out["optuna_best"]["n_trials"] == 3
    assert out["optuna_best"]["best_val_loss"] == 0.61


def test_optuna_reuses_cached_best(tmp_path, monkeypatch: Any) -> None:
    study = _FakeStudy()
    _install_fake_optuna(monkeypatch, study)
    payload = {
        "params": {"lr": 1.5e-4, "weight_decay": 2e-3, "dropout": 0.25},
        "best_val_loss": 0.42,
        "n_trials": 8,
        "cache_identity": optuna_cache_identity(),
    }
    (tmp_path / "optuna_best.json").write_text(json.dumps(payload), encoding="utf-8")
    cfg = {
        "run_optuna": True,
        "optuna_refresh": False,
        "lr": 1e-4,
        "dropout": 0.3,
        "weight_decay": 1e-3,
    }
    out = optuna_search(
        cfg,
        n_features=4,
        train_loader=object(),  # type: ignore[arg-type]
        val_loader=object(),  # type: ignore[arg-type]
        device=torch.device("cpu"),
        cache_dir=tmp_path,
        train_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no train")),
    )
    assert study.optimize_calls == 0
    assert out["lr"] == 1.5e-4
    assert out["dropout"] == 0.25
    assert out["weight_decay"] == 2e-3
    assert out["optuna_best"]["best_val_loss"] == 0.42


def test_optuna_stale_cache_reruns_search(tmp_path, monkeypatch: Any) -> None:
    study = _FakeStudy()
    _install_fake_optuna(monkeypatch, study)
    payload = {
        "params": {"lr": 1.5e-4, "weight_decay": 2e-3, "dropout": 0.25},
        "best_val_loss": 0.42,
        "n_trials": 8,
        "cache_identity": {
            "feature_contract_version": "transformer_btcusd_mtf_fusion_v10",
            "feature_fingerprint": "deadbeef",
            "horizon_keys": ["h10m", "h30m", "h1h", "h2h"],
            "n_classes": 3,
        },
    }
    (tmp_path / "optuna_best.json").write_text(json.dumps(payload), encoding="utf-8")

    def fake_train(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"ok": True, "best_val_loss": 0.61, "history": [(1, 0.7, 0.61)]}

    def fake_factory(n_features: int, config: Dict[str, Any]) -> MtfFusionTransformer:
        return MtfFusionTransformer(
            n_features=n_features, d_model=16, nhead=2, num_layers=1, max_len=8
        )

    cfg = {
        "run_optuna": True,
        "optuna_refresh": False,
        "optuna_trials": 1,
        "optuna_trial_epochs": 1,
        "lr": 1e-4,
        "dropout": 0.3,
        "weight_decay": 1e-3,
    }
    out = optuna_search(
        cfg,
        n_features=4,
        train_loader=object(),  # type: ignore[arg-type]
        val_loader=object(),  # type: ignore[arg-type]
        device=torch.device("cpu"),
        cache_dir=tmp_path,
        train_fn=fake_train,
        model_factory=fake_factory,
    )
    assert study.optimize_calls == 1
    assert out["lr"] == 2e-4
    assert out["optuna_best"]["cache_identity"] == optuna_cache_identity()


def test_optuna_refresh_ignores_cache(tmp_path, monkeypatch: Any) -> None:
    study = _FakeStudy()
    _install_fake_optuna(monkeypatch, study)
    payload = {
        "params": {"lr": 1.5e-4, "weight_decay": 2e-3, "dropout": 0.25},
        "best_val_loss": 0.42,
        "n_trials": 8,
    }
    (tmp_path / "optuna_best.json").write_text(json.dumps(payload), encoding="utf-8")

    def fake_train(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"ok": True, "best_val_loss": 0.61, "history": [(1, 0.7, 0.61)]}

    def fake_factory(n_features: int, config: Dict[str, Any]) -> MtfFusionTransformer:
        return MtfFusionTransformer(
            n_features=n_features, d_model=16, nhead=2, num_layers=1, max_len=8
        )

    cfg = {
        "run_optuna": True,
        "optuna_refresh": True,
        "optuna_trials": 1,
        "optuna_trial_epochs": 1,
        "lr": 1e-4,
        "dropout": 0.3,
        "weight_decay": 1e-3,
    }
    out = optuna_search(
        cfg,
        n_features=4,
        train_loader=object(),  # type: ignore[arg-type]
        val_loader=object(),  # type: ignore[arg-type]
        device=torch.device("cpu"),
        cache_dir=tmp_path,
        train_fn=fake_train,
        model_factory=fake_factory,
    )
    assert study.optimize_calls == 1
    assert out["lr"] == 2e-4


def test_optuna_trial_exception_keeps_search_going(monkeypatch: Any) -> None:
    study = _FakeStudy()
    _install_fake_optuna(monkeypatch, study)

    def boom(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise RuntimeError("cuda oom")

    def fake_factory(n_features: int, config: Dict[str, Any]) -> MtfFusionTransformer:
        return MtfFusionTransformer(
            n_features=n_features, d_model=16, nhead=2, num_layers=1, max_len=8
        )

    cfg = {
        "run_optuna": True,
        "optuna_trials": 1,
        "lr": 1e-4,
        "dropout": 0.3,
        "weight_decay": 1e-3,
    }
    out = optuna_search(
        cfg,
        n_features=4,
        train_loader=object(),  # type: ignore[arg-type]
        val_loader=object(),  # type: ignore[arg-type]
        device=torch.device("cpu"),
        train_fn=boom,
        model_factory=fake_factory,
    )
    assert study.optimize_calls == 1
    assert out["lr"] == 1e-4
    assert "optuna_best" not in out


def test_materialize_skips_huge_arrays() -> None:
    from scripts.colab.mtf_fusion_research import materialize_windows_if_fits

    class _HugeView:
        nbytes = 3 * 1024 * 1024 * 1024

    blob = _HugeView()
    out = materialize_windows_if_fits({"5m": blob}, enabled=True)  # type: ignore[arg-type]
    assert out["5m"] is blob
    small = np.ones((2, 2), dtype=np.float32)
    copied = materialize_windows_if_fits({"5m": small}, enabled=True)
    assert copied["5m"].flags.writeable
    assert copied["5m"].shape == small.shape
