"""Write stub transformer bundle artifacts without PyTorch (local dev/testing)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_ONNX_PKG = Path("D:/onnx_pkg")
if _ONNX_PKG.is_dir() and str(_ONNX_PKG) not in sys.path:
    sys.path.insert(0, str(_ONNX_PKG))

from feature_store.transformer_btcusd_15m.contract import (
    CONTINUOUS_LABEL_COLS,
    DEFAULT_TRAINING_CONFIG,
    FEATURE_COLS,
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_ONNX_FILENAME,
)
from feature_store.transformer_btcusd_15m.inference import feature_config_from_training_export

BUNDLE_DIR = ROOT / "agent" / "model_storage" / "JackSparrow_Transformer_BTCUSD"


def _build_stub_onnx(onnx_path: Path, window_len: int, n_features: int) -> None:
    import onnx
    from onnx import TensorProto, helper

    n_cont = len(CONTINUOUS_LABEL_COLS)
    n_regime = 4
    flat_dim = window_len * n_features

    window = helper.make_tensor_value_info(
        "window", TensorProto.FLOAT, [None, window_len, n_features]
    )
    continuous_pred = helper.make_tensor_value_info(
        "continuous_pred", TensorProto.FLOAT, [None, n_cont]
    )
    regime_logits = helper.make_tensor_value_info(
        "regime_logits", TensorProto.FLOAT, [None, n_regime]
    )

    shape_vec = helper.make_tensor("shape_vec", TensorProto.INT64, [1], [0])
    neg_one = helper.make_tensor("neg_one", TensorProto.INT64, [1], [-1])

    shape_node = helper.make_node("Shape", ["window"], ["full_shape"], name="shape0")
    batch_node = helper.make_node(
        "Gather", ["full_shape", "shape_vec"], ["batch_size"], axis=0, name="gather_batch"
    )
    reshape_shape = helper.make_node(
        "Concat",
        ["batch_size", "flat_dim"],
        ["reshape_shape"],
        axis=0,
        name="concat_reshape",
    )
    flat_dim_t = helper.make_tensor("flat_dim", TensorProto.INT64, [1], [flat_dim])
    reshape_node = helper.make_node(
        "Reshape", ["window", "reshape_shape"], ["flat"], name="reshape"
    )

    w_cont = helper.make_tensor(
        "w_cont",
        TensorProto.FLOAT,
        [flat_dim, n_cont],
        [0.0] * (flat_dim * n_cont),
    )
    w_reg = helper.make_tensor(
        "w_reg",
        TensorProto.FLOAT,
        [flat_dim, n_regime],
        [0.0] * (flat_dim * n_regime),
    )
    b_reg = helper.make_tensor(
        "b_reg", TensorProto.FLOAT, [n_regime], [0.0, 1.0, 0.0, 0.0]
    )

    cont_node = helper.make_node("MatMul", ["flat", "w_cont"], ["continuous_pred"], name="matmul_cont")
    reg_lin = helper.make_node("MatMul", ["flat", "w_reg"], ["reg_lin"], name="matmul_reg")
    reg_node = helper.make_node("Add", ["reg_lin", "b_reg"], ["regime_logits"], name="add_reg")

    graph = helper.make_graph(
        nodes=[shape_node, batch_node, reshape_shape, reshape_node, cont_node, reg_lin, reg_node],
        name="stub_transformer",
        inputs=[window],
        outputs=[continuous_pred, regime_logits],
        initializer=[shape_vec, neg_one, flat_dim_t, w_cont, w_reg, b_reg],
    )
    model = helper.make_model(
        graph,
        opset_imports=[helper.make_opsetid("", 17)],
    )
    onnx.checker.check_model(model)
    onnx.save(model, str(onnx_path))


def main() -> None:
    config = dict(DEFAULT_TRAINING_CONFIG)
    window_len = int(config["window_len"])
    n_features = len(FEATURE_COLS)
    label_mean = np.zeros(len(CONTINUOUS_LABEL_COLS), dtype=np.float64)
    label_std = np.ones(len(CONTINUOUS_LABEL_COLS), dtype=np.float64)
    q_edges = np.array([0.001, 0.003, 0.006], dtype=np.float64)

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    onnx_path = BUNDLE_DIR / TRANSFORMER_ONNX_FILENAME
    cfg_path = BUNDLE_DIR / TRANSFORMER_FEATURE_CONFIG_FILENAME

    _build_stub_onnx(onnx_path, window_len, n_features)
    feature_config = feature_config_from_training_export(
        feature_cols=FEATURE_COLS,
        window_len=window_len,
        label_mean=label_mean,
        label_std=label_std,
        q_edges=q_edges,
        config=config,
    )
    cfg_path.write_text(json.dumps(feature_config, indent=2), encoding="utf-8")

    import onnxruntime as ort

    sess = ort.InferenceSession(str(onnx_path))
    dummy = np.zeros((1, window_len, n_features), dtype=np.float32)
    cont, reg = sess.run(None, {"window": dummy})
    print(
        json.dumps(
            {
                "onnx": str(onnx_path),
                "feature_config": str(cfg_path),
                "continuous_shape": list(cont.shape),
                "regime_shape": list(reg.shape),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
