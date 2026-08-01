"""Training loop and model definitions for per-TF BTCUSD transformer Colab workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from feature_store.transformer_btcusd.contract import (
    CONTINUOUS_LABEL_COLS,
    RETURN_COL,
    TRANSFORMER_FEATURE_CONFIG_FILENAME,
    TRANSFORMER_METADATA_FILENAME,
    onnx_filename_for_resolution,
)
from feature_store.transformer_btcusd.inference import (
    feature_config_from_training_export,
    metadata_from_training_export,
    zscore_window,
)


def set_training_seed(seed: int) -> None:
    """Set RNG seeds for reproducible Colab runs."""
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def build_windows(
    df: pd.DataFrame,
    feature_cols: Sequence[str],
    label_cols: Sequence[str],
    window_len: int,
    stride: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """Stack overlapping feature windows and end-of-window labels."""
    x_list: List[np.ndarray] = []
    y_list: List[np.ndarray] = []
    values = df[list(feature_cols)].values.astype(np.float32)
    labels = df[list(label_cols)].values.astype(np.float64)
    for end in range(window_len, len(df), stride):
        start = end - window_len
        x_list.append(values[start:end])
        y_list.append(labels[end - 1])
    return np.array(x_list), np.array(y_list)


def split_purged_windows(
    x_all: np.ndarray,
    y_all: np.ndarray,
    *,
    train_frac: float,
    val_frac: float,
    embargo_bars: int,
) -> Dict[str, np.ndarray]:
    """Time-ordered train/val/test split with embargo gaps between segments."""
    n = len(x_all)
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)
    embargo = embargo_bars

    splits = {
        "x_train": x_all[:train_end],
        "y_train": y_all[:train_end],
        "x_val": x_all[train_end + embargo : val_end],
        "y_val": y_all[train_end + embargo : val_end],
        "x_test": x_all[val_end + embargo : n],
        "y_test": y_all[val_end + embargo : n],
    }
    if len(splits["x_train"]) == 0 or len(splits["x_val"]) == 0:
        raise ValueError(
            f"Insufficient windows after split: train={len(splits['x_train'])}, "
            f"val={len(splits['x_val'])}, test={len(splits['x_test'])}"
        )
    return splits


def fit_label_stats(y_train: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Train-split mean/std for label standardization (NaNs excluded from fit)."""
    mean = np.nanmean(y_train, axis=0)
    std = np.nanstd(y_train, axis=0) + 1e-9
    return mean, std


def standardize_labels(
    y: np.ndarray,
    label_mean: np.ndarray,
    label_std: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Z-score labels and build per-target validity masks."""
    mask = (~np.isnan(y)).astype(np.float32)
    yz = np.where(np.isnan(y), 0.0, (y - label_mean) / label_std).astype(np.float32)
    return yz, mask


def fit_vol_regime_edges(
    y_train: np.ndarray,
    quantiles: Sequence[float],
) -> np.ndarray:
    """Quantile cutoffs for future_volatility regime classification."""
    fv_idx = CONTINUOUS_LABEL_COLS.index("future_volatility")
    return np.nanquantile(y_train[:, fv_idx], quantiles)


def to_vol_regime(y: np.ndarray, q_edges: np.ndarray) -> np.ndarray:
    """Map raw labels to 4-class volatility regime indices."""
    fv_idx = CONTINUOUS_LABEL_COLS.index("future_volatility")
    return np.digitize(y[:, fv_idx], q_edges).astype(np.int64)


class WindowDataset(Dataset):
    """Per-window z-scored features with standardized multi-task targets."""

    def __init__(
        self,
        x: np.ndarray,
        y_z: np.ndarray,
        mask: np.ndarray,
        regime: np.ndarray,
    ) -> None:
        self.x = x
        self.y_z = y_z
        self.mask = mask
        self.regime = regime

    def __len__(self) -> int:
        return len(self.x)

    def __getitem__(
        self, i: int
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        w = zscore_window(self.x[i])
        return (
            torch.tensor(w, dtype=torch.float32),
            torch.tensor(self.y_z[i], dtype=torch.float32),
            torch.tensor(self.mask[i], dtype=torch.float32),
            torch.tensor(self.regime[i], dtype=torch.long),
        )


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 512) -> None:
        super().__init__()
        self.pe = nn.Parameter(torch.randn(1, max_len, d_model) * 0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1), :]


class MarketTransformer(nn.Module):
    """Multi-task market-understanding encoder (continuous + vol-regime heads)."""

    def __init__(
        self,
        n_features: int,
        d_model: int,
        nhead: int,
        num_layers: int,
        dropout: float,
        max_len: int,
        n_continuous: int,
        n_regime_classes: int = 4,
    ) -> None:
        super().__init__()
        self.input_proj = nn.Linear(n_features, d_model)
        self.pos_enc = PositionalEncoding(d_model, max_len=max_len)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_model * 4,
            dropout=dropout,
            batch_first=True,
            activation="gelu",
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.norm = nn.LayerNorm(d_model)
        shared_dim = d_model // 2
        self.shared = nn.Sequential(
            nn.Linear(d_model, shared_dim),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.continuous_head = nn.Linear(shared_dim, n_continuous)
        self.regime_head = nn.Linear(shared_dim, n_regime_classes)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        h = self.input_proj(x)
        h = self.pos_enc(h)
        h = self.encoder(h)
        h = self.norm(h)
        pooled = h[:, -1, :]
        shared = self.shared(pooled)
        return self.continuous_head(shared), self.regime_head(shared)


def compute_multitask_loss(
    continuous_pred: torch.Tensor,
    regime_logits: torch.Tensor,
    yb_z: torch.Tensor,
    mb: torch.Tensor,
    rb: torch.Tensor,
    log_vars: nn.Parameter,
    *,
    n_continuous: int,
) -> torch.Tensor:
    """Uncertainty-weighted multi-task loss over continuous heads + regime CE."""
    losses: List[torch.Tensor] = []
    for j in range(n_continuous):
        diff = (continuous_pred[:, j] - yb_z[:, j]) ** 2
        masked = (diff * mb[:, j]).sum() / (mb[:, j].sum() + 1e-6)
        precision = torch.exp(-log_vars[j])
        losses.append(precision * masked + log_vars[j])
    ce = nn.functional.cross_entropy(regime_logits, rb)
    precision = torch.exp(-log_vars[n_continuous])
    losses.append(precision * ce + log_vars[n_continuous])
    return sum(losses)


@dataclass
class TrainingResult:
    """Best checkpoint and training metadata."""

    best_val_loss: float
    best_epoch: int
    model_state: Dict[str, torch.Tensor]
    log_vars: torch.Tensor
    history: List[Tuple[int, float, float]] = field(default_factory=list)


def train_transformer(
    model: MarketTransformer,
    train_loader: DataLoader,
    val_loader: DataLoader,
    config: Dict[str, Any],
    *,
    device: torch.device,
    n_continuous: int | None = None,
) -> TrainingResult:
    """Train with AdamW, optional LR scheduler, and early stopping."""
    n_cont = n_continuous or len(CONTINUOUS_LABEL_COLS)
    log_vars = nn.Parameter(torch.zeros(n_cont + 1, device=device))
    params = list(model.parameters()) + [log_vars]
    optimizer = torch.optim.AdamW(
        params,
        lr=config["lr"],
        weight_decay=config["weight_decay"],
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="min",
        factor=0.5,
        patience=5,
    )

    best_val = float("inf")
    best_epoch = 0
    best_state: Optional[Dict[str, torch.Tensor]] = None
    best_log_vars: Optional[torch.Tensor] = None
    epochs_since_improvement = 0
    history: List[Tuple[int, float, float]] = []

    for epoch in range(config["epochs"]):
        model.train()
        train_loss = 0.0
        for xb, yb_z, mb, rb in train_loader:
            xb, yb_z, mb, rb = (
                xb.to(device),
                yb_z.to(device),
                mb.to(device),
                rb.to(device),
            )
            optimizer.zero_grad()
            cont, reg = model(xb)
            loss = compute_multitask_loss(
                cont, reg, yb_z, mb, rb, log_vars, n_continuous=n_cont
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optimizer.step()
            train_loss += float(loss.item())

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb_z, mb, rb in val_loader:
                xb, yb_z, mb, rb = (
                    xb.to(device),
                    yb_z.to(device),
                    mb.to(device),
                    rb.to(device),
                )
                cont, reg = model(xb)
                val_loss += float(
                    compute_multitask_loss(
                        cont, reg, yb_z, mb, rb, log_vars, n_continuous=n_cont
                    ).item()
                )
        val_loss /= max(len(val_loader), 1)
        train_loss /= max(len(train_loader), 1)
        history.append((epoch + 1, train_loss, val_loss))

        prev_lr = optimizer.param_groups[0]["lr"]
        scheduler.step(val_loss)
        new_lr = optimizer.param_groups[0]["lr"]
        lr_note = f" lr->{new_lr:.2e}" if new_lr < prev_lr else ""

        marker = ""
        if val_loss < best_val:
            best_val = val_loss
            best_epoch = epoch + 1
            epochs_since_improvement = 0
            best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
            best_log_vars = log_vars.detach().cpu()
            marker = " *best*"
        else:
            epochs_since_improvement += 1

        print(
            f"epoch {epoch + 1:03d}  train={train_loss:.4f}  val={val_loss:.4f}{marker}{lr_note}"
        )

        if (
            config.get("early_stopping_enabled", False)
            and epochs_since_improvement >= config.get("early_stop_patience", 10)
        ):
            print(
                f"Early stopping: no val improvement in "
                f"{config['early_stop_patience']} epochs."
            )
            break

    if best_state is None or best_log_vars is None:
        raise RuntimeError("Training did not produce a checkpoint")

    return TrainingResult(
        best_val_loss=best_val,
        best_epoch=best_epoch,
        model_state=best_state,
        log_vars=best_log_vars,
        history=history,
    )


@dataclass
class TargetMetrics:
    name: str
    mae: float
    corr: float
    n: int


def evaluate_continuous_targets(
    model: MarketTransformer,
    loader: DataLoader,
    *,
    device: torch.device,
    label_mean: np.ndarray,
    label_std: np.ndarray,
    label_cols: Sequence[str] = CONTINUOUS_LABEL_COLS,
) -> List[TargetMetrics]:
    """Per-target MAE and correlation on un-standardized predictions."""
    model.eval()
    pred_z_list: List[np.ndarray] = []
    true_z_list: List[np.ndarray] = []
    mask_list: List[np.ndarray] = []

    with torch.no_grad():
        for xb, yb_z, mb, _rb in loader:
            xb = xb.to(device)
            cont, _ = model(xb)
            pred_z_list.append(cont.cpu().numpy())
            true_z_list.append(yb_z.numpy())
            mask_list.append(mb.numpy())

    pred_z = np.concatenate(pred_z_list, axis=0)
    true_z = np.concatenate(true_z_list, axis=0)
    mask = np.concatenate(mask_list, axis=0)

    pred = pred_z * label_std + label_mean
    true = true_z * label_std + label_mean

    metrics: List[TargetMetrics] = []
    for j, name in enumerate(label_cols):
        valid = mask[:, j] > 0
        if valid.sum() < 2:
            continue
        p = pred[valid, j]
        t = true[valid, j]
        mae = float(np.mean(np.abs(p - t)))
        corr = float(np.corrcoef(p, t)[0, 1]) if len(p) > 1 else 0.0
        metrics.append(TargetMetrics(name=name, mae=mae, corr=corr, n=int(valid.sum())))
    return metrics


def print_target_metrics(metrics: Sequence[TargetMetrics], title: str = "") -> None:
    """Pretty-print per-target evaluation lines."""
    if title:
        print(title)
    for m in metrics:
        print(f"  {m.name:28s}  MAE={m.mae:.5f}  corr={m.corr:+.3f}  n={m.n}")


def print_return_metrics(metrics: Sequence[TargetMetrics]) -> None:
    """Highlight future_return correlation (primary signal quality check)."""
    by_name = {m.name: m for m in metrics}
    m = by_name.get(RETURN_COL)
    if m is None:
        print(f"  {RETURN_COL:28s}  (no valid samples)")
        return
    print(f"Primary return correlation:")
    print(f"  {m.name:28s}  corr={m.corr:+.3f}  MAE={m.mae:.5f}  n={m.n}")


def evaluate_regime_head(
    model: MarketTransformer,
    loader: DataLoader,
    *,
    device: torch.device,
) -> Tuple[np.ndarray, np.ndarray]:
    """Collect regime predictions and ground truth for sklearn reports."""
    model.eval()
    pred_list: List[int] = []
    true_list: List[int] = []
    with torch.no_grad():
        for xb, _yb_z, _mb, rb in loader:
            xb = xb.to(device)
            _, regime_logits = model(xb)
            pred_list.extend(torch.argmax(regime_logits, dim=1).cpu().numpy().tolist())
            true_list.extend(rb.numpy().tolist())
    return np.array(pred_list), np.array(true_list)


def check_export_quality_gate(
    metrics: Sequence[TargetMetrics],
    min_return_corr: float,
) -> None:
    """Raise if future_return test correlation is below export floor."""
    by_name = {m.name: m for m in metrics}
    m = by_name.get(RETURN_COL)
    if m is None:
        raise RuntimeError(f"Export blocked: no valid {RETURN_COL} test samples")
    if m.corr < min_return_corr:
        raise RuntimeError(
            f"Export blocked: {RETURN_COL} test corr {m.corr:.4f} "
            f"< floor {min_return_corr:.4f}"
        )


def export_transformer_bundle(
    model: MarketTransformer,
    export_dir: Path,
    *,
    device: torch.device,
    window_len: int,
    n_features: int,
    feature_cols: Sequence[str],
    label_mean: np.ndarray,
    label_std: np.ndarray,
    q_edges: np.ndarray,
    config: Dict[str, Any],
    test_metrics: Sequence[TargetMetrics] | None = None,
    verify: bool = True,
    enforce_quality_gate: bool = True,
) -> Tuple[Path, Path, Path]:
    """Export ONNX + feature_config.json + metadata_transformer.json."""
    resolution = str(config.get("resolution") or "15m")
    min_corr = float(config.get("min_export_return_corr") or 0.02)
    if enforce_quality_gate and test_metrics is not None:
        check_export_quality_gate(test_metrics, min_corr)

    export_dir.mkdir(parents=True, exist_ok=True)
    onnx_name = onnx_filename_for_resolution(resolution)
    onnx_path = export_dir / onnx_name
    cfg_path = export_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME
    meta_path = export_dir / TRANSFORMER_METADATA_FILENAME

    dummy = torch.randn(1, window_len, n_features, device=device)
    torch.onnx.export(
        model,
        dummy,
        str(onnx_path),
        input_names=["window"],
        output_names=["continuous_pred", "regime_logits"],
        dynamic_axes={
            "window": {0: "batch"},
            "continuous_pred": {0: "batch"},
            "regime_logits": {0: "batch"},
        },
        opset_version=17,
        export_params=True,
        dynamo=False,
    )

    if verify:
        import onnx as onnx_lib
        import onnxruntime as ort

        check_model = onnx_lib.load(str(onnx_path), load_external_data=False)
        external = [
            init.name for init in check_model.graph.initializer if init.data_location == 1
        ]
        if external:
            raise RuntimeError(
                f"ONNX export left {len(external)} weights external "
                f"(e.g. {external[0]}). Model will not run standalone."
            )

        sess = ort.InferenceSession(str(onnx_path))
        onnx_cont, onnx_reg = sess.run(None, {"window": dummy.cpu().numpy()})
        with torch.no_grad():
            torch_cont, torch_reg = model(dummy)
        diff_cont = np.abs(onnx_cont - torch_cont.cpu().numpy()).max()
        diff_reg = np.abs(onnx_reg - torch_reg.cpu().numpy()).max()
        print(f"ONNX verify continuous_pred max diff: {diff_cont:.2e}")
        print(f"ONNX verify regime_logits max diff: {diff_reg:.2e}")
        print(f"ONNX output shapes: {onnx_cont.shape}, {onnx_reg.shape}")

    metrics_dict = {}
    if test_metrics:
        metrics_dict = {m.name: {"mae": m.mae, "corr": m.corr, "n": m.n} for m in test_metrics}

    feature_config = feature_config_from_training_export(
        feature_cols=feature_cols,
        window_len=window_len,
        label_mean=label_mean,
        label_std=label_std,
        q_edges=q_edges,
        config=config,
    )
    cfg_path.write_text(json.dumps(feature_config, indent=2), encoding="utf-8")

    metadata = metadata_from_training_export(
        resolution=resolution,
        label_mean=label_mean,
        label_std=label_std,
        config=config,
        test_metrics=metrics_dict,
    )
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return onnx_path, cfg_path, meta_path
