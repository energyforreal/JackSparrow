"""Tests for shared-encoder fusion model and walk-forward grading."""

from __future__ import annotations

import numpy as np
import torch

from feature_store.transformer_btcusd.contract import (
    FUSION_DIRECTION_CARDINALITY,
    FUSION_GRADE_HIGH,
    FUSION_GRADE_LOW,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_WINDOW_LEN,
    N_FUSION_HORIZONS,
)
from scripts.colab.mtf_fusion_model import MtfFusionTransformer, compute_fusion_loss
from scripts.colab.mtf_fusion_research import grade_horizon, softmax_np


def test_fusion_forward_shapes() -> None:
    n_feat = 8
    model = MtfFusionTransformer(n_features=n_feat, max_len=FUSION_WINDOW_LEN)
    windows = [
        torch.randn(2, FUSION_WINDOW_LEN, n_feat) for _ in FUSION_INPUT_RESOLUTIONS
    ]
    outs = model(*windows)
    assert len(outs) == N_FUSION_HORIZONS + 1
    for i in range(N_FUSION_HORIZONS):
        assert outs[i].shape == (2, FUSION_DIRECTION_CARDINALITY)
    assert outs[-1].shape == (2, 5)
    weights = model.fusion_weights()
    assert torch.isclose(weights.sum(), torch.tensor(1.0), atol=1e-5)
    assert torch.all(weights >= 0)


def test_fusion_loss_is_ce_only() -> None:
    logits = tuple(torch.zeros(4, 3) for _ in range(4)) + (torch.zeros(4, 5),)
    labels = torch.tensor([[2, 2, 1, 0], [0, 1, 2, 2], [1, 1, 1, 1], [2, 0, 0, 2]])
    loss = compute_fusion_loss(logits, labels)
    assert torch.isfinite(loss)
    assert float(loss) > 0


def test_grade_horizon_thresholds() -> None:
    assert grade_horizon(balanced_acc=0.50, ece=0.04) == FUSION_GRADE_HIGH
    assert grade_horizon(balanced_acc=0.42, ece=0.20) != FUSION_GRADE_HIGH
    assert grade_horizon(balanced_acc=0.30, ece=0.01) == FUSION_GRADE_LOW
    # Unstable folds cannot be HIGH
    assert (
        grade_horizon(balanced_acc=0.50, ece=0.04, fold_std=0.12)
        != FUSION_GRADE_HIGH
    )


def test_softmax_np() -> None:
    p = softmax_np(np.array([[1.0, 0.0, 0.0]]))
    assert p.shape == (1, 3)
    assert abs(p.sum() - 1.0) < 1e-6
