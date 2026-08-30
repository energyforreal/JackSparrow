"""Tests for shared-encoder fusion model and walk-forward grading."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from agent.models.fusion_node import validate_fusion_v11_outputs
from feature_store.transformer_btcusd.contract import (
    FUSION_DIRECTION_CARDINALITY,
    FUSION_GRADE_HIGH,
    FUSION_GRADE_LOW,
    FUSION_GRADE_MEDIUM,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_WINDOW_LEN,
    N_FUSION_HORIZONS,
    ONNX_OUTPUT_NAMES_V11,
)
from scripts.colab.mtf_fusion_model import (
    MtfFusionTransformer,
    compute_fusion_loss,
    fusion_model_from_config,
    inverse_frequency_class_weights,
)
from scripts.colab.mtf_fusion_research import (
    fusion_ready_to_promote,
    grade_horizon,
    softmax_np,
)


def test_fusion_forward_shapes() -> None:
    n_feat = 8
    model = MtfFusionTransformer(n_features=n_feat, max_len=FUSION_WINDOW_LEN)
    windows = [
        torch.randn(2, FUSION_WINDOW_LEN, n_feat) for _ in FUSION_INPUT_RESOLUTIONS
    ]
    outs = model(*windows)
    assert len(outs) == N_FUSION_HORIZONS + 1
    assert N_FUSION_HORIZONS == 3
    for i in range(N_FUSION_HORIZONS):
        assert outs[i].shape == (2, FUSION_DIRECTION_CARDINALITY)
        assert outs[i].shape[-1] == 2
    assert outs[-1].shape == (2, 5)
    weights = model.fusion_weights()
    assert torch.isclose(weights.sum(), torch.tensor(1.0), atol=1e-5)
    assert torch.all(weights >= 0)


def test_fusion_loss_ignores_neutral() -> None:
    logits = tuple(torch.zeros(4, 2) for _ in range(3)) + (torch.zeros(4, 5),)
    labels = torch.tensor(
        [[1, 1, 0], [0, -1, 1], [-1, -1, -1], [1, 0, 0]], dtype=torch.long
    )
    loss = compute_fusion_loss(logits, labels)
    assert torch.isfinite(loss)
    all_ignored = torch.full((4, 3), -1, dtype=torch.long)
    ignored_loss = compute_fusion_loss(logits, all_ignored)
    assert float(ignored_loss) == 0.0
    smooth = compute_fusion_loss(logits, labels, label_smoothing=0.05)
    assert torch.isfinite(smooth)


def test_fusion_loss_horizon_weights_downweight_h2h() -> None:
    good = torch.tensor([[-4.0, 4.0], [-4.0, 4.0]])
    bad = torch.tensor([[4.0, -4.0], [4.0, -4.0]])
    logits = (good, good, bad, torch.zeros(2, 5))
    labels = torch.ones(2, 3, dtype=torch.long)
    equal = compute_fusion_loss(logits, labels)
    down = compute_fusion_loss(logits, labels, horizon_weights=[1.0, 1.0, 0.1])
    assert float(down) < float(equal)


def test_fusion_model_from_config_passes_dropout() -> None:
    cfg = {"d_model": 16, "nhead": 2, "num_layers": 1, "dropout": 0.4, "window_len": 8}
    model = fusion_model_from_config(4, cfg)
    assert model.shared[2].p == pytest.approx(0.4)


def test_class_weights_skip_ignored() -> None:
    y = np.array([[0, -1, 1], [0, 1, -1], [-1, -1, 1]], dtype=np.int64)
    w = inverse_frequency_class_weights(y, 2)
    assert w.shape == (2,)
    assert np.all(np.isfinite(w))
    assert abs(float(w.mean()) - 1.0) < 1e-5


def test_grade_horizon_thresholds() -> None:
    assert grade_horizon(balanced_acc=0.58, ece=0.04) == FUSION_GRADE_HIGH
    assert grade_horizon(balanced_acc=0.55, ece=0.20) == FUSION_GRADE_MEDIUM
    assert grade_horizon(balanced_acc=0.50, ece=0.01) == FUSION_GRADE_LOW
    assert grade_horizon(balanced_acc=0.42, ece=0.20) != FUSION_GRADE_HIGH
    assert (
        grade_horizon(balanced_acc=0.60, ece=0.04, fold_std=0.12)
        == FUSION_GRADE_MEDIUM
    )


def test_softmax_np_two_class() -> None:
    p = softmax_np(np.array([[1.0, 0.0]]))
    assert p.shape == (1, 2)
    assert abs(p.sum() - 1.0) < 1e-6


def test_validate_fusion_v11_outputs_rejects_h10m() -> None:
    try:
        validate_fusion_v11_outputs(list(ONNX_OUTPUT_NAMES_V11) + ["h10m_dir_logits"])
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "h10m_dir_logits" in str(exc)


def test_validate_fusion_v11_outputs_rejects_three_logits() -> None:
    names = list(ONNX_OUTPUT_NAMES_V11)
    shapes = [[None, 3], [None, 2], [None, 2], [None, 5]]
    try:
        validate_fusion_v11_outputs(names, shapes)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "2-logit" in str(exc)


def test_fusion_ready_to_promote_requires_medium_on_wf_and_test() -> None:
    wf = {
        "mean": {"h30m": 0.56, "h1h": 0.51, "h2h": 0.50},
        "std": {"h30m": 0.02, "h1h": 0.02, "h2h": 0.02},
    }
    test = {
        "h30m": {"balanced_acc": 0.57, "ece": 0.10},
        "h1h": {"balanced_acc": 0.51, "ece": 0.10},
        "h2h": {"balanced_acc": 0.49, "ece": 0.10},
    }
    gates = {
        "horizons": {
            "h30m": {"validation_confidence": FUSION_GRADE_MEDIUM},
            "h1h": {"validation_confidence": FUSION_GRADE_LOW},
            "h2h": {"validation_confidence": FUSION_GRADE_LOW},
        }
    }
    result = fusion_ready_to_promote(wf, test, gates)
    assert result["ready"] is True
    assert result["heads"] == ["h30m"]
    low = fusion_ready_to_promote(
        {"mean": {"h30m": 0.51, "h1h": 0.50, "h2h": 0.50}, "std": {}},
        test,
        gates,
    )
    assert low["ready"] is False


def test_local_v11_smoke_train_and_policy_hold() -> None:
    """Few-step smoke: ignore mask, 2-logit heads, HOLD on low probability."""
    n_feat = 4
    n = 16
    model = MtfFusionTransformer(
        n_features=n_feat, d_model=16, nhead=2, num_layers=1, max_len=8
    )
    windows = [torch.randn(n, 8, n_feat) for _ in FUSION_INPUT_RESOLUTIONS]
    labels = torch.randint(0, 2, (n, 3))
    labels[:4, 0] = -1
    opt = torch.optim.SGD(model.parameters(), lr=1e-3)
    model.train()
    for _ in range(2):
        opt.zero_grad()
        outs = model(*windows)
        loss = compute_fusion_loss(outs, labels)
        assert torch.isfinite(loss)
        loss.backward()
        opt.step()
    model.eval()
    with torch.no_grad():
        outs = model(*windows)
    assert len(outs) == 4
    for i in range(3):
        assert outs[i].shape == (n, 2)
    from agent.core.fusion_policy import evaluate_horizon_forecast, rung_from_logits
    from feature_store.transformer_btcusd.contract import FUSION_GRADE_HIGH

    low_p = rung_from_logits(
        "h30m",
        [0.0, 0.02],
        temperature=1.0,
        min_probability=0.55,
        validation_confidence=FUSION_GRADE_HIGH,
    )
    assert low_p.accepted is False
    verdict = evaluate_horizon_forecast(
        {k: [0.0, 0.02] for k in ("h30m", "h1h", "h2h")},
        gates={
            "horizons": {
                k: {
                    "temperature": 1.0,
                    "validation_confidence": FUSION_GRADE_HIGH,
                    "min_probability": 0.55,
                }
                for k in ("h30m", "h1h", "h2h")
            }
        },
    )
    assert verdict.signal == "HOLD"
