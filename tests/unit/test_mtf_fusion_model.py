"""Tests for shared-encoder fusion model and walk-forward grading."""

from __future__ import annotations

import json
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
    LABEL_V2_DIRECTION_CARDINALITY,
    LABEL_V2_REG_FIELDS,
    N_FUSION_HORIZONS,
    ONNX_OUTPUT_NAMES_V11,
    ONNX_OUTPUT_NAMES_V12,
    ONNX_OUTPUT_NAMES_V13,
    ONNX_OUTPUT_NAMES_V15,
    RESOLUTION_MINUTES,
    default_fusion_training_config,
    fusion_window_len,
    fusion_window_lens,
    FEATURE_CONTRACT_VERSION_V11,
    FEATURE_CONTRACT_VERSION_V14,
    FEATURE_CONTRACT_VERSION_V15,
    LABEL_V2_HORIZON_KEYS,
    onnx_output_names_for_contract,
)
from scripts.colab.mtf_fusion_model import (
    FusionTrainLabels,
    MtfFusionDataset,
    MtfFusionTransformer,
    compute_fusion_loss,
    fusion_lr_scheduler,
    fusion_model_from_config,
    fusion_class_weight_tensor,
    inverse_frequency_class_weights,
    resolve_fusion_class_weights,
    tensor_to_numpy,
    step_fusion_scheduler,
    train_mtf_fusion,
    unpack_fusion_batch,
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
    n_path = N_FUSION_HORIZONS * len(LABEL_V2_REG_FIELDS)
    assert len(ONNX_OUTPUT_NAMES_V13) == 19
    assert len(outs) == len(ONNX_OUTPUT_NAMES_V13)
    assert N_FUSION_HORIZONS == 3
    for i in range(N_FUSION_HORIZONS):
        assert outs[i].shape == (2, LABEL_V2_DIRECTION_CARDINALITY)
        assert outs[i].shape[-1] == 3
    for i in range(N_FUSION_HORIZONS, N_FUSION_HORIZONS + n_path):
        assert outs[i].shape == (2, 1)
    assert outs[-1].shape == (2, 5)
    weights = model.fusion_weights()
    assert torch.isclose(weights.sum(), torch.tensor(1.0), atol=1e-5)
    assert torch.all(weights >= 0)


def test_fusion_loss_masks_invalid_dir() -> None:
    logits = tuple(torch.zeros(4, 3) for _ in range(3)) + (torch.zeros(4, 5),)
    labels = torch.tensor(
        [[1, 1, 0], [0, -1, 2], [-1, -1, -1], [2, 0, 0]], dtype=torch.long
    )
    loss = compute_fusion_loss(logits, labels)
    assert torch.isfinite(loss)
    all_ignored = torch.full((4, 3), -1, dtype=torch.long)
    ignored_loss = compute_fusion_loss(logits, all_ignored)
    assert float(ignored_loss) == 0.0
    smooth = compute_fusion_loss(logits, labels, label_smoothing=0.05)
    assert torch.isfinite(smooth)


def test_fusion_loss_trains_neutral_class() -> None:
    logits = tuple(torch.zeros(2, 3) for _ in range(3)) + (torch.zeros(2, 5),)
    labels = torch.ones(2, 3, dtype=torch.long)
    loss = compute_fusion_loss(logits, labels)
    assert torch.isfinite(loss)
    assert float(loss) > 0.0


def test_fusion_loss_masks_nan_path() -> None:
    n_path = N_FUSION_HORIZONS * len(LABEL_V2_REG_FIELDS)
    dir_logits = tuple(torch.zeros(2, 3) for _ in range(3))
    path_outs = tuple(torch.zeros(2, 1) for _ in range(n_path))
    outputs = dir_logits + path_outs + (torch.zeros(2, 5),)
    labels = torch.ones(2, 3, dtype=torch.long)
    y_reg = torch.full((2, 3, len(LABEL_V2_REG_FIELDS)), float("nan"))
    y_reg[0, 0, 0] = 1.5
    loss = compute_fusion_loss(outputs, labels, path_labels=y_reg)
    assert torch.isfinite(loss)
    all_nan = torch.full((2, 3, len(LABEL_V2_REG_FIELDS)), float("nan"))
    ce_only = compute_fusion_loss(dir_logits + (torch.zeros(2, 5),), labels)
    masked = compute_fusion_loss(outputs, labels, path_labels=all_nan)
    assert torch.isfinite(masked)
    assert float(masked) == pytest.approx(float(ce_only), rel=1e-5, abs=1e-5)


def test_fusion_loss_horizon_weights_downweight_h2h() -> None:
    good = torch.tensor([[-4.0, 0.0, 4.0], [-4.0, 0.0, 4.0]])
    bad = torch.tensor([[4.0, 0.0, -4.0], [4.0, 0.0, -4.0]])
    logits = (good, good, bad, torch.zeros(2, 5))
    labels = torch.full((2, 3), 2, dtype=torch.long)
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


def test_resolve_fusion_class_weights_respects_config() -> None:
    y = np.array([[0, 1, 2], [0, 0, 1]], dtype=np.int64)
    assert resolve_fusion_class_weights(y, 3, {"use_class_weights": False}) is None
    on = resolve_fusion_class_weights(y, 3, {"use_class_weights": True})
    assert on is not None
    assert on.shape == (3,)
    assert fusion_class_weight_tensor(y, 3, {"use_class_weights": False}) is None


def test_tensor_to_numpy_preserves_shape() -> None:
    t = torch.arange(6, dtype=torch.float32).view(2, 3)
    arr = tensor_to_numpy(t)
    assert arr.shape == (2, 3)
    assert arr.dtype == np.float32
    assert np.allclose(arr, np.arange(6, dtype=np.float32).reshape(2, 3))


def test_fusion_loss_zero_path_weights_is_ce_only() -> None:
    n_h = 4
    n_f = len(LABEL_V2_REG_FIELDS)
    dir_logits = tuple(torch.zeros(3, 3) for _ in range(n_h))
    path_outs = tuple(torch.full((3, 1), 10.0) for _ in range(n_h * n_f))
    outputs = dir_logits + path_outs + (torch.zeros(3, 5),)
    labels = torch.ones(3, n_h, dtype=torch.long)
    y_path = torch.ones(3, n_h, n_f)
    from feature_store.transformer_btcusd.contract import (
        LABEL_V2_DIRECTION_ONLY_PATH_LOSS_WEIGHTS,
    )

    with_path_off = compute_fusion_loss(
        outputs,
        labels,
        path_labels=y_path,
        path_task_weights=dict(LABEL_V2_DIRECTION_ONLY_PATH_LOSS_WEIGHTS),
    )
    ce_only = compute_fusion_loss(dir_logits + (torch.zeros(3, 5),), labels)
    assert torch.isclose(with_path_off, ce_only, atol=1e-6)


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


def test_onnx_v12_names_stay_frozen() -> None:
    from feature_store.transformer_btcusd.contract import (
        FEATURE_CONTRACT_VERSION_V12,
        onnx_output_names_for_contract,
    )

    assert len(ONNX_OUTPUT_NAMES_V12) == 13
    assert list(ONNX_OUTPUT_NAMES_V12[:3]) == list(ONNX_OUTPUT_NAMES_V11[:3])
    assert "h30m_ret" in ONNX_OUTPUT_NAMES_V12
    assert "h2h_mae" in ONNX_OUTPUT_NAMES_V12
    assert ONNX_OUTPUT_NAMES_V12[-1] == "tf_fusion_logits"
    assert onnx_output_names_for_contract(FEATURE_CONTRACT_VERSION_V12) == (
        ONNX_OUTPUT_NAMES_V12
    )


def test_onnx_v13_names_are_research_only() -> None:
    from feature_store.transformer_btcusd.contract import (
        FEATURE_CONTRACT_VERSION_V13,
        onnx_output_names_for_contract,
    )

    assert len(ONNX_OUTPUT_NAMES_V11) == 4
    assert list(ONNX_OUTPUT_NAMES_V13[:3]) == list(ONNX_OUTPUT_NAMES_V11[:3])
    assert "h30m_ret" in ONNX_OUTPUT_NAMES_V13
    assert "h30m_long_mae" in ONNX_OUTPUT_NAMES_V13
    assert "h2h_short_mfe" in ONNX_OUTPUT_NAMES_V13
    assert "h2h_mae" not in ONNX_OUTPUT_NAMES_V13
    assert ONNX_OUTPUT_NAMES_V13[-1] == "tf_fusion_logits"
    assert len(ONNX_OUTPUT_NAMES_V13) == 19
    assert onnx_output_names_for_contract(FEATURE_CONTRACT_VERSION_V13) == (
        ONNX_OUTPUT_NAMES_V13
    )
    assert onnx_output_names_for_contract(
        "transformer_btcusd_mtf_fusion_v11", resolution="mtf_fusion"
    ) == ONNX_OUTPUT_NAMES_V11


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
    assert result["ready"] is False
    assert result["reason"] == "research_v15_not_live"
    assert result["heads"] == []
    assert result["research_heads"] == ["h30m"]
    assert result["detail"]["h30m"]["test_grade"] == FUSION_GRADE_MEDIUM
    assert result["detail"]["h30m"]["validation_grade"] == FUSION_GRADE_MEDIUM
    low_wf = fusion_ready_to_promote(
        {"mean": {"h30m": 0.51, "h1h": 0.50, "h2h": 0.50}, "std": {}},
        test,
        gates,
    )
    assert low_wf["ready"] is False
    assert low_wf["research_heads"] == []
    weak_test = {
        "h30m": {"balanced_acc": 0.51, "ece": 0.10},
        "h1h": {"balanced_acc": 0.51, "ece": 0.10},
        "h2h": {"balanced_acc": 0.49, "ece": 0.10},
    }
    assert fusion_ready_to_promote(wf, weak_test, gates)["research_heads"] == []
    low_val = {
        "horizons": {
            "h30m": {"validation_confidence": FUSION_GRADE_LOW},
            "h1h": {"validation_confidence": FUSION_GRADE_LOW},
            "h2h": {"validation_confidence": FUSION_GRADE_LOW},
        }
    }
    assert fusion_ready_to_promote(wf, test, low_val)["research_heads"] == []


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


def test_local_v13_smoke_train_and_v11_policy_hold() -> None:
    """Few-step smoke: 3-class+path heads; live policy still 2-logit HOLD."""
    n_feat = 4
    n = 16
    model = MtfFusionTransformer(
        n_features=n_feat, d_model=16, nhead=2, num_layers=1, max_len=8
    )
    windows = [torch.randn(n, 8, n_feat) for _ in FUSION_INPUT_RESOLUTIONS]
    labels = torch.randint(0, 3, (n, 3))
    labels[:4, 0] = -1
    path = torch.randn(n, 3, len(LABEL_V2_REG_FIELDS))
    path[:2, 0, 0] = float("nan")
    opt = torch.optim.SGD(model.parameters(), lr=1e-3)
    model.train()
    for _ in range(2):
        opt.zero_grad()
        outs = model(*windows)
        loss = compute_fusion_loss(outs, labels, path_labels=path)
        assert torch.isfinite(loss)
        loss.backward()
        opt.step()
    model.eval()
    with torch.no_grad():
        outs = model(*windows)
    assert len(outs) == len(ONNX_OUTPUT_NAMES_V13)
    for i in range(3):
        assert outs[i].shape == (n, 3)
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
    assert outs[0].shape == (n, 3)
    assert outs[-1].shape == (n, 5)
    assert len(outs) == len(ONNX_OUTPUT_NAMES_V13)


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
        n_horizons=4,
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
    assert feature_cfg["feature_contract_version"].endswith("v15")
    assert feature_cfg["onnx_output_names"] == list(ONNX_OUTPUT_NAMES_V15)
    assert feature_cfg["ready_to_promote"] is False
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


def test_dataset_appends_path_labels() -> None:
    n_feat = 3
    n = 4
    windows = {
        res: np.ones((n, 8, n_feat), dtype=np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    packed = FusionTrainLabels(
        np.zeros((n, 3), dtype=np.int64),
        np.ones((n, 3, len(LABEL_V2_REG_FIELDS)), dtype=np.float32),
    )
    ds = MtfFusionDataset(windows, packed)
    row = ds[0]
    assert len(row) == len(FUSION_INPUT_RESOLUTIONS) + 2
    assert row[-2].dtype == torch.long
    assert row[-1].shape == (3, len(LABEL_V2_REG_FIELDS))
    assert row[-1].dtype == torch.float32


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


def test_default_fusion_training_config_budget() -> None:
    cfg = default_fusion_training_config()
    assert cfg["batch_size"] == 128
    assert cfg["epochs"] == 40
    assert cfg["early_stop_patience"] == 8
    assert cfg["lr_schedule"] == "plateau"
    assert cfg["run_optuna"] is False
    assert cfg["use_state_embeddings"] is True
    assert cfg["run_leave_one_group_out"] is False
    assert cfg["horizon_keys"] == list(LABEL_V2_HORIZON_KEYS)
    assert cfg["horizon_loss_weights"] == [1.0, 1.0, 1.0, 1.0]
    assert cfg["experiment"] == "later_direction_only"
    assert cfg["use_class_weights"] is False
    path_w = cfg["path_loss_weights"]
    assert path_w["dir"] == 1.0
    assert path_w["ret"] == 0.0
    assert path_w["long_mfe"] == 0.0
    assert path_w["long_mae"] == 0.0
    assert path_w["short_mfe"] == 0.0
    assert path_w["short_mae"] == 0.0
    from feature_store.transformer_btcusd.contract import LABEL_V2_PATH_LOSS_WEIGHTS

    assert LABEL_V2_PATH_LOSS_WEIGHTS["ret"] == 1.0
    model = fusion_model_from_config(8, cfg)
    assert model.n_horizons == 4
    assert len(model.dir_heads) == 4


def test_plateau_schedule_lowers_lr_when_val_stalls() -> None:
    param = torch.nn.Parameter(torch.zeros(1))
    opt = torch.optim.AdamW([param], lr=1e-4)
    sched = fusion_lr_scheduler(opt, "plateau", epochs=40)
    assert isinstance(sched, torch.optim.lr_scheduler.ReduceLROnPlateau)
    start = float(opt.param_groups[0]["lr"])
    for _ in range(6):
        step_fusion_scheduler(sched, 1.0)
    assert float(opt.param_groups[0]["lr"]) == pytest.approx(start * 0.5)


def test_train_mtf_fusion_plateau_stays_finite() -> None:
    n_feat = 4
    model = MtfFusionTransformer(
        n_features=n_feat, d_model=16, nhead=2, num_layers=1, max_len=8
    )
    windows = {
        res: np.random.randn(8, 8, n_feat).astype(np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    labels = np.random.randint(0, 3, size=(8, 3), dtype=np.int64)
    from torch.utils.data import DataLoader

    loader = DataLoader(MtfFusionDataset(windows, labels), batch_size=4, shuffle=False)
    hist = train_mtf_fusion(
        model,
        loader,
        loader,
        device=torch.device("cpu"),
        epochs=2,
        lr=1e-3,
        weight_decay=0.0,
        patience=8,
        lr_schedule="plateau",
    )
    assert hist["ok"] is True
    assert math.isfinite(hist["best_val_loss"])
    assert hist["last_lr"] == pytest.approx(1e-3)


def test_fusion_forward_with_state_embeddings() -> None:
    n_feat = 6
    n = 3
    width = 8
    model = MtfFusionTransformer(
        n_features=n_feat,
        d_model=16,
        nhead=2,
        num_layers=1,
        max_len=width,
        use_state_embeddings=True,
    )
    windows = [torch.randn(n, width, n_feat) for _ in FUSION_INPUT_RESOLUTIONS]
    candle = [torch.randint(0, 13, (n, width)) for _ in FUSION_INPUT_RESOLUTIONS]
    chart = [torch.randint(0, 9, (n, width)) for _ in FUSION_INPUT_RESOLUTIONS]
    outs = model(*windows, *candle, *chart)
    assert len(outs) == len(ONNX_OUTPUT_NAMES_V13)
    assert outs[0].shape == (n, LABEL_V2_DIRECTION_CARDINALITY)
    assert outs[-1].shape == (n, 5)
    model.zero_candle_embed = True
    model.zero_chart_embed = True
    outs_z = model(*windows, *candle, *chart)
    assert outs_z[0].shape == outs[0].shape


def test_dataset_appends_state_ids() -> None:
    n_feat = 4
    n = 3
    windows = {
        res: np.ones((n, 8, n_feat), dtype=np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    candle = {
        res: np.zeros((n, 8), dtype=np.int64) for res in FUSION_INPUT_RESOLUTIONS
    }
    chart = {
        res: np.ones((n, 8), dtype=np.int64) for res in FUSION_INPUT_RESOLUTIONS
    }
    labels = np.zeros((n, 3), dtype=np.int64)
    ds = MtfFusionDataset(
        windows, labels, candle_ids=candle, chart_ids=chart
    )
    row = ds[0]
    assert len(row) == len(FUSION_INPUT_RESOLUTIONS) * 3 + 1
    assert row[0].dtype == torch.float32
    assert row[len(FUSION_INPUT_RESOLUTIONS)].dtype == torch.long
    model = MtfFusionTransformer(
        n_features=n_feat, d_model=16, nhead=2, num_layers=1, max_len=8,
        use_state_embeddings=True,
    )
    batch = next(iter(
        torch.utils.data.DataLoader(ds, batch_size=2, shuffle=False)
    ))
    windows_b, y_dir, path = unpack_fusion_batch(batch)
    assert path is None
    assert y_dir.shape[0] == 2
    outs = model(*windows_b)
    assert outs[0].shape == (2, 3)


def test_fusion_node_rejects_v14_contract(tmp_path) -> None:
    from agent.models.fusion_node import FusionModelNode
    from feature_store.transformer_btcusd.contract import (
        FUSION_MODEL_FAMILY,
        TRANSFORMER_FEATURE_CONFIG_FILENAME,
        TRANSFORMER_METADATA_FILENAME,
    )

    (tmp_path / TRANSFORMER_FEATURE_CONFIG_FILENAME).write_text(
        json.dumps({"feature_contract_version": FEATURE_CONTRACT_VERSION_V14}),
        encoding="utf-8",
    )
    (tmp_path / TRANSFORMER_METADATA_FILENAME).write_text(
        json.dumps({"model_family": FUSION_MODEL_FAMILY}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="is not"):
        FusionModelNode.from_metadata_path(tmp_path / TRANSFORMER_METADATA_FILENAME)


def test_v14_onnx_names_match_v13_heads() -> None:
    assert onnx_output_names_for_contract(FEATURE_CONTRACT_VERSION_V14) == (
        ONNX_OUTPUT_NAMES_V13
    )
    assert FEATURE_CONTRACT_VERSION_V14 != FEATURE_CONTRACT_VERSION_V11


def test_onnx_v15_names_are_four_research_heads() -> None:
    assert list(ONNX_OUTPUT_NAMES_V15[:4]) == [
        "h10m_dir_logits",
        "h15m_dir_logits",
        "h30m_dir_logits",
        "h1h_dir_logits",
    ]
    assert "h2h_dir_logits" not in ONNX_OUTPUT_NAMES_V15
    assert "h10m_ret" in ONNX_OUTPUT_NAMES_V15
    assert "h15m_long_mae" in ONNX_OUTPUT_NAMES_V15
    assert ONNX_OUTPUT_NAMES_V15[-1] == "tf_fusion_logits"
    assert len(ONNX_OUTPUT_NAMES_V15) == 25
    assert onnx_output_names_for_contract(FEATURE_CONTRACT_VERSION_V15) == (
        ONNX_OUTPUT_NAMES_V15
    )


def test_knock_out_feature_group_zeros_columns() -> None:
    from feature_store.transformer_btcusd.contract import fusion_feature_cols_v14
    from scripts.colab.mtf_fusion_research import knock_out_feature_group

    cols = list(fusion_feature_cols_v14())
    n_feat = len(cols)
    windows = {
        res: np.ones((2, 4, n_feat), dtype=np.float32)
        for res in FUSION_INPUT_RESOLUTIONS
    }
    knocked = knock_out_feature_group(windows, "price")
    idx = cols.index("ret_1")
    assert float(knocked["5m"][0, 0, idx]) == 0.0
    other = [i for i, name in enumerate(cols) if name != "ret_1"]
    assert float(knocked["5m"][0, 0, other[0]]) == 1.0
    assert float(windows["5m"][0, 0, idx]) == 1.0
