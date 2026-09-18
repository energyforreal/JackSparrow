"""Tests for shared-encoder fusion model and walk-forward grading."""

from __future__ import annotations

import math

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
    FUSION_TARGET_WINDOW_MINUTES,
    FUSION_WINDOW_LEN,
    N_FUSION_HORIZONS,
    ONNX_OUTPUT_NAMES_V11,
    RESOLUTION_MINUTES,
    fusion_window_len,
    fusion_window_lens,
)
from scripts.colab.mtf_fusion_model import (
    MtfFusionDataset,
    MtfFusionTransformer,
    compute_fusion_loss,
    fusion_model_from_config,
    inverse_frequency_class_weights,
    train_mtf_fusion,
)
from scripts.colab.mtf_fusion_research import (
    development_prefix,
    fusion_ready_to_promote,
    grade_horizon,
    make_loader,
    softmax_np,
)


def test_fusion_window_span_table() -> None:
    target = FUSION_TARGET_WINDOW_MINUTES
    print("resolution  minutes/bar  window_len  span_min  err")
    for res in FUSION_INPUT_RESOLUTIONS:
        minutes = RESOLUTION_MINUTES[res]
        width = fusion_window_len(res)
        span = width * minutes
        err = span - target
        print(f"{res:10} {minutes:11d} {width:10d} {span:8d} {err:4d}")
        assert abs(err) <= minutes
    assert fusion_window_lens()["5m"] == FUSION_WINDOW_LEN
    assert FUSION_WINDOW_LEN == fusion_window_len("5m")
    assert max(fusion_window_lens().values()) == FUSION_WINDOW_LEN


def test_fusion_forward_shapes() -> None:
    n_feat = 8
    lens = fusion_window_lens()
    model = MtfFusionTransformer(n_features=n_feat, max_len=max(lens.values()))
    windows = [
        torch.randn(2, int(lens[res]), n_feat) for res in FUSION_INPUT_RESOLUTIONS
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
    assert model.pos_enc.pe.size(1) == 8
    assert model.scale_proj.out_features == 16


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


def test_fusion_ready_to_promote_requires_medium_on_wf_test_and_val() -> None:
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
    assert result["detail"]["h30m"]["test_grade"] == FUSION_GRADE_MEDIUM
    assert result["detail"]["h30m"]["validation_grade"] == FUSION_GRADE_MEDIUM
    low_wf = fusion_ready_to_promote(
        {"mean": {"h30m": 0.51, "h1h": 0.50, "h2h": 0.50}, "std": {}},
        test,
        gates,
    )
    assert low_wf["ready"] is False
    weak_test = {
        "h30m": {"balanced_acc": 0.51, "ece": 0.10},
        "h1h": {"balanced_acc": 0.51, "ece": 0.10},
        "h2h": {"balanced_acc": 0.49, "ece": 0.10},
    }
    assert fusion_ready_to_promote(wf, weak_test, gates)["ready"] is False
    low_val = {
        "horizons": {
            "h30m": {"validation_confidence": FUSION_GRADE_LOW},
            "h1h": {"validation_confidence": FUSION_GRADE_LOW},
            "h2h": {"validation_confidence": FUSION_GRADE_LOW},
        }
    }
    assert fusion_ready_to_promote(wf, test, low_val)["ready"] is False


def test_development_prefix_keeps_embargo_rows() -> None:
    n = 100
    windows = {
        res: np.arange(n, dtype=np.float32).reshape(n, 1, 1)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    labels = np.zeros((n, 3), dtype=np.int64)
    dev_w, dev_y = development_prefix(
        windows, labels, train_frac=0.70, val_frac=0.15
    )
    assert len(dev_y) == 85
    assert len(dev_w["5m"]) == 85
    assert float(dev_w["5m"][-1, 0, 0]) == 84.0


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


def test_batched_encoder_matches_looped_encode_tf_eval() -> None:
    n_feat = 6
    lens = fusion_window_lens()
    model = MtfFusionTransformer(
        n_features=n_feat,
        d_model=16,
        nhead=2,
        num_layers=1,
        max_len=max(lens.values()),
    )
    model.eval()
    windows = [
        torch.randn(3, int(lens[res]), n_feat) for res in FUSION_INPUT_RESOLUTIONS
    ]
    with torch.no_grad():
        looped = torch.stack(
            [model.encode_tf(w, i) for i, w in enumerate(windows)], dim=1
        )
        batched = model.encode_all_tfs(windows)
        outs_loop = []
        combined = (looped * model.fusion_weights().view(1, 5, 1)).sum(dim=1)
        shared = model.shared(combined)
        for head in model.dir_heads:
            outs_loop.append(head(shared))
        outs_fwd = model(*windows)
    torch.testing.assert_close(batched, looped, atol=1e-5, rtol=1e-5)
    for i in range(3):
        torch.testing.assert_close(outs_fwd[i], outs_loop[i], atol=1e-5, rtol=1e-5)


def test_dataset_forward_per_tf_shapes() -> None:
    n_feat = 5
    n = 4
    lens = fusion_window_lens()
    windows = {
        res: np.random.randn(n, int(lens[res]), n_feat).astype(np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    labels = np.zeros((n, 3), dtype=np.int64)
    ds = MtfFusionDataset(windows, labels)
    row = ds[0]
    for i, res in enumerate(FUSION_INPUT_RESOLUTIONS):
        assert row[i].shape == (int(lens[res]), n_feat)
    model = MtfFusionTransformer(
        n_features=n_feat,
        d_model=16,
        nhead=2,
        num_layers=1,
        max_len=max(lens.values()),
    )
    batch = [
        torch.stack([ds[j][i] for j in range(n)], dim=0)
        for i in range(len(FUSION_INPUT_RESOLUTIONS))
    ]
    for tensor, res in zip(batch, FUSION_INPUT_RESOLUTIONS):
        assert tensor.shape == (n, int(lens[res]), n_feat)
    outs = model(*batch)
    assert outs[0].shape == (n, 2)
    assert outs[-1].shape == (n, 5)


def test_export_fusion_bundle_per_tf_input_shapes(tmp_path) -> None:
    import json

    from scripts.colab.mtf_fusion_research import export_fusion_bundle

    n_feat = 4
    lens = fusion_window_lens()
    dummy = [
        torch.randn(1, int(lens[res]), n_feat) for res in FUSION_INPUT_RESOLUTIONS
    ]
    for tensor, res in zip(dummy, FUSION_INPUT_RESOLUTIONS):
        assert tensor.shape == (1, int(lens[res]), n_feat)
    model = MtfFusionTransformer(
        n_features=n_feat,
        d_model=16,
        nhead=2,
        num_layers=1,
        max_len=max(lens.values()),
    )
    try:
        import onnx  # noqa: F401
        from onnx import defs as _onnx_defs  # noqa: F401
    except ImportError:
        pytest.skip("onnx is not installed")
    onnx_path, cfg_path, _meta = export_fusion_bundle(
        model,
        tmp_path,
        n_features=n_feat,
        window_lens=lens,
        config={"symbol": "BTCUSD", "window_lens": lens},
        gates={},
        fusion_weights=[0.2] * 5,
    )
    feature_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert feature_cfg["window_lens"] == {res: int(lens[res]) for res in lens}
    assert feature_cfg["target_window_minutes"] == FUSION_TARGET_WINDOW_MINUTES
    try:
        import onnxruntime as ort
    except ImportError:
        pytest.skip("onnxruntime not installed")
    session = ort.InferenceSession(
        str(onnx_path), providers=["CPUExecutionProvider"]
    )
    for inp, res in zip(session.get_inputs(), FUSION_INPUT_RESOLUTIONS):
        assert inp.shape[1] == int(lens[res]), (inp.name, inp.shape, res)


def test_dataset_ram_getitem_shares_storage() -> None:
    probe = np.ones((2, 2), dtype=np.float32)
    try:
        torch.from_numpy(probe)
    except RuntimeError:
        pytest.skip("torch/numpy bridge unavailable in this environment")
    n_feat = 3
    n = 4
    windows = {
        res: np.ones((n, 8, n_feat), dtype=np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    labels = np.zeros((n, 3), dtype=np.int64)
    ds = MtfFusionDataset(windows, labels)
    row = ds.windows["5m"][0]
    assert row.flags.writeable
    tensor = ds[0][0]
    assert np.shares_memory(tensor.numpy(), row)


def test_make_loader_windows_in_ram() -> None:
    n_feat = 3
    windows = {
        res: np.ones((6, 8, n_feat), dtype=np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    labels = np.zeros((6, 3), dtype=np.int64)
    loader = make_loader(
        windows,
        labels,
        batch_size=2,
        shuffle=False,
        windows_in_ram=True,
        pin_memory=False,
        num_workers=0,
    )
    batch = next(iter(loader))
    assert len(batch) == len(FUSION_INPUT_RESOLUTIONS) + 1
    assert batch[0].shape == (2, 8, n_feat)
    assert batch[0].dtype == torch.float32


def test_dataset_accepts_torch_windows() -> None:
    n_feat = 3
    n = 4
    windows = {
        res: torch.ones((n, 8, n_feat), dtype=torch.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    labels = torch.zeros((n, 3), dtype=torch.long)
    ds = MtfFusionDataset(windows, labels)
    row = ds[0]
    assert len(row) == len(FUSION_INPUT_RESOLUTIONS) + 1
    assert row[0].shape == (8, n_feat)
    assert row[0].dtype == torch.float32


def test_loader_runtime_kwargs_cpu_disables_workers() -> None:
    from scripts.colab.mtf_fusion_research import loader_runtime_kwargs

    cfg = {
        "pin_memory": True,
        "dataloader_workers": 2,
        "windows_in_ram": True,
        "prefetch_factor": 4,
    }
    kw = loader_runtime_kwargs(cfg, torch.device("cpu"))
    assert kw["num_workers"] == 0
    assert kw["pin_memory"] is False
    assert kw["prefetch_factor"] == 4


def test_train_amp_flag_on_cpu_stays_finite() -> None:
    n_feat = 4
    model = MtfFusionTransformer(
        n_features=n_feat, d_model=16, nhead=2, num_layers=1, max_len=8
    )
    windows = {
        res: np.random.randn(8, 8, n_feat).astype(np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    labels = np.random.randint(0, 2, size=(8, 3), dtype=np.int64)
    from torch.utils.data import DataLoader

    loader = DataLoader(MtfFusionDataset(windows, labels), batch_size=4, shuffle=False)
    hist = train_mtf_fusion(
        model,
        loader,
        loader,
        device=torch.device("cpu"),
        epochs=1,
        lr=1e-3,
        weight_decay=0.0,
        patience=2,
        amp=True,
    )
    assert hist["ok"] is True
    assert math.isfinite(hist["best_val_loss"])
