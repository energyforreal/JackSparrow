"""Training loop and model definitions for per-TF BTCUSD transformer Colab workflow."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_CARDINALITY,
    CANDLE_CLASS_COL,
    CANDLE_EMBED_DIM,
    CONTINUOUS_LABEL_COLS,
    EXPORT_QUALITY_DISCLAIMER,
    N_AUX_CLASS_HEADS,
    ONNX_OUTPUT_NAMES,
    PROMOTION_REGIME_ACCURACY,
    PROMOTION_VOL_CORR,
    STRUCTURE_OUTCOME_CARDINALITY,
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
    *,
    class_col: str = CANDLE_CLASS_COL,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Stack overlapping continuous, candle-class, and label windows."""
    x_list: List[np.ndarray] = []
    cat_list: List[np.ndarray] = []
    y_list: List[np.ndarray] = []
    values = df[list(feature_cols)].values.astype(np.float32)
    class_ids = df[class_col].values.astype(np.int64)
    labels = df[list(label_cols)].values.astype(np.float64)
    for end in range(window_len, len(df), stride):
        start = end - window_len
        x_list.append(values[start:end])
        cat_list.append(class_ids[start:end])
        y_list.append(labels[end - 1])
    return np.array(x_list), np.array(cat_list, dtype=np.int64), np.array(y_list)


def build_class_targets(
    df: pd.DataFrame,
    class_col: str,
    window_len: int,
    stride: int,
) -> np.ndarray:
    """Integer class id at each window's last bar (aligned with ``build_windows``)."""
    ids = pd.to_numeric(df[class_col], errors="coerce").fillna(0).to_numpy(dtype=np.int64)
    out: List[int] = []
    for end in range(window_len, len(df), stride):
        out.append(int(ids[end - 1]))
    return np.array(out, dtype=np.int64)


def inverse_frequency_class_weights(
    class_ids: np.ndarray,
    n_classes: int,
) -> np.ndarray:
    """Inverse-frequency weights (mean-normalized) for imbalanced CE heads."""
    counts = np.bincount(
        np.asarray(class_ids, dtype=np.int64), minlength=int(n_classes)
    ).astype(np.float64)
    counts = np.maximum(counts, 1.0)
    weights = 1.0 / counts
    weights = weights * (float(n_classes) / weights.sum())
    return weights.astype(np.float32)


def split_purged_windows(
    arrays: Mapping[str, np.ndarray],
    *,
    train_frac: float,
    val_frac: float,
    embargo_bars: int,
) -> Dict[str, Dict[str, np.ndarray]]:
    """Time-ordered train/val/test split with embargo gaps between segments."""
    if not arrays:
        raise ValueError("split_purged_windows requires at least one array")
    lengths = {k: len(v) for k, v in arrays.items()}
    n = next(iter(lengths.values()))
    if any(length != n for length in lengths.values()):
        raise ValueError(f"Array length mismatch: {lengths}")
    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)
    embargo = embargo_bars
    slices = {
        "train": slice(0, train_end),
        "val": slice(train_end + embargo, val_end),
        "test": slice(val_end + embargo, n),
    }
    splits = {
        split: {k: v[sl] for k, v in arrays.items()} for split, sl in slices.items()
    }
    first_key = next(iter(arrays))
    if len(splits["train"][first_key]) == 0 or len(splits["val"][first_key]) == 0:
        raise ValueError(
            f"Insufficient windows after split: train={len(splits['train'][first_key])}, "
            f"val={len(splits['val'][first_key])}, test={len(splits['test'][first_key])}"
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
        x_cat: np.ndarray,
        y_z: np.ndarray,
        mask: np.ndarray,
        regime: np.ndarray,
        structure_outcome: np.ndarray | None = None,
        future_candle: np.ndarray | None = None,
    ) -> None:
        self.x = x
        self.x_cat = x_cat
        self.y_z = y_z
        self.mask = mask
        self.regime = regime
        n = len(x)
        self.structure_outcome = (
            np.asarray(structure_outcome, dtype=np.int64)
            if structure_outcome is not None
            else np.zeros(n, dtype=np.int64)
        )
        self.future_candle = (
            np.asarray(future_candle, dtype=np.int64)
            if future_candle is not None
            else np.zeros(n, dtype=np.int64)
        )

    def __len__(self) -> int:
        return len(self.x)

    def __getitem__(
        self, i: int
    ) -> Tuple[
        torch.Tensor,
        torch.Tensor,
        torch.Tensor,
        torch.Tensor,
        torch.Tensor,
        torch.Tensor,
        torch.Tensor,
    ]:
        w = zscore_window(self.x[i])
        return (
            torch.tensor(w, dtype=torch.float32),
            torch.tensor(self.x_cat[i], dtype=torch.long),
            torch.tensor(self.y_z[i], dtype=torch.float32),
            torch.tensor(self.mask[i], dtype=torch.float32),
            torch.tensor(self.regime[i], dtype=torch.long),
            torch.tensor(self.structure_outcome[i], dtype=torch.long),
            torch.tensor(self.future_candle[i], dtype=torch.long),
        )


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 512) -> None:
        super().__init__()
        self.pe = nn.Parameter(torch.randn(1, max_len, d_model) * 0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1), :]


class MarketTransformer(nn.Module):
    """Multi-task encoder: continuous path, vol regime, structure, next candle."""

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
        n_structure_classes: int = STRUCTURE_OUTCOME_CARDINALITY,
        n_candle_classes: int = CANDLE_CLASS_CARDINALITY,
        candle_embed_dim: int = CANDLE_EMBED_DIM,
    ) -> None:
        super().__init__()
        self.candle_embed = nn.Embedding(n_candle_classes, candle_embed_dim)
        self.input_proj = nn.Linear(n_features + candle_embed_dim, d_model)
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
        self.structure_head = nn.Linear(shared_dim, n_structure_classes)
        self.future_candle_head = nn.Linear(shared_dim, n_candle_classes)

    def forward(
        self, x: torch.Tensor, candle_class_ids: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        embed = self.candle_embed(candle_class_ids)
        x = torch.cat([x, embed], dim=-1)
        h = self.input_proj(x)
        h = self.pos_enc(h)
        h = self.encoder(h)
        h = self.norm(h)
        pooled = h[:, -1, :]
        shared = self.shared(pooled)
        return (
            self.continuous_head(shared),
            self.regime_head(shared),
            self.structure_head(shared),
            self.future_candle_head(shared),
        )


def compute_multitask_loss(
    continuous_pred: torch.Tensor,
    regime_logits: torch.Tensor,
    structure_logits: torch.Tensor,
    future_candle_logits: torch.Tensor,
    yb_z: torch.Tensor,
    mb: torch.Tensor,
    rb: torch.Tensor,
    structure_y: torch.Tensor,
    future_candle_y: torch.Tensor,
    log_vars: nn.Parameter,
    *,
    n_continuous: int,
    continuous_loss_weights: Sequence[float] | None = None,
    candle_class_weights: torch.Tensor | None = None,
) -> torch.Tensor:
    """Uncertainty-weighted MSE plus vol/structure/candle CE heads."""
    if continuous_loss_weights is not None:
        weights = [float(w) for w in continuous_loss_weights]
        if len(weights) != n_continuous:
            raise ValueError(
                f"continuous_loss_weights length {len(weights)} != n_continuous {n_continuous}"
            )
    else:
        weights = [1.0 for _ in range(n_continuous)]

    losses: List[torch.Tensor] = []
    for j in range(n_continuous):
        task_w = float(weights[j])
        if task_w <= 0.0:
            continue
        diff = (continuous_pred[:, j] - yb_z[:, j]) ** 2
        masked = (diff * mb[:, j]).sum() / (mb[:, j].sum() + 1e-6)
        precision = torch.exp(-log_vars[j])
        losses.append(task_w * (precision * masked + log_vars[j]))

    ce_terms = (
        (regime_logits, rb, None),
        (structure_logits, structure_y, None),
        (future_candle_logits, future_candle_y, candle_class_weights),
    )
    for offset, (logits, target, cls_w) in enumerate(ce_terms):
        idx = n_continuous + offset
        if cls_w is not None:
            ce = nn.functional.cross_entropy(logits, target, weight=cls_w)
        else:
            ce = nn.functional.cross_entropy(logits, target)
        precision = torch.exp(-log_vars[idx])
        losses.append(precision * ce + log_vars[idx])
    return sum(losses)


@dataclass
class TrainingResult:
    """Best checkpoint and training metadata."""

    best_val_loss: float
    best_epoch: int
    model_state: Dict[str, torch.Tensor]
    log_vars: torch.Tensor
    history: List[Tuple[int, float, float]] = field(default_factory=list)
    stopped_at_epoch: int = 0


def _batch_to_device(
    batch: Sequence[torch.Tensor],
    device: torch.device,
) -> Tuple[torch.Tensor, ...]:
    return tuple(t.to(device) for t in batch)


def train_transformer(
    model: MarketTransformer,
    train_loader: DataLoader,
    val_loader: DataLoader,
    config: Dict[str, Any],
    *,
    device: torch.device,
    n_continuous: int | None = None,
    candle_class_weights: Sequence[float] | np.ndarray | None = None,
) -> TrainingResult:
    """Train with AdamW, optional LR scheduler, and early stopping."""
    n_cont = n_continuous or len(CONTINUOUS_LABEL_COLS)
    loss_weights = config.get("continuous_loss_weights")
    log_vars = nn.Parameter(torch.zeros(n_cont + N_AUX_CLASS_HEADS, device=device))
    params = list(model.parameters()) + [log_vars]
    candle_w: Optional[torch.Tensor] = None
    if candle_class_weights is not None:
        candle_w = torch.as_tensor(candle_class_weights, dtype=torch.float32, device=device)
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
        for batch in train_loader:
            xb, xcat, yb_z, mb, rb, so, fc = _batch_to_device(batch, device)
            optimizer.zero_grad()
            cont, reg, struct_logits, candle_logits = model(xb, xcat)
            loss = compute_multitask_loss(
                cont,
                reg,
                struct_logits,
                candle_logits,
                yb_z,
                mb,
                rb,
                so,
                fc,
                log_vars,
                n_continuous=n_cont,
                continuous_loss_weights=loss_weights,
                candle_class_weights=candle_w,
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optimizer.step()
            train_loss += float(loss.item())

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for batch in val_loader:
                xb, xcat, yb_z, mb, rb, so, fc = _batch_to_device(batch, device)
                cont, reg, struct_logits, candle_logits = model(xb, xcat)
                val_loss += float(
                    compute_multitask_loss(
                        cont,
                        reg,
                        struct_logits,
                        candle_logits,
                        yb_z,
                        mb,
                        rb,
                        so,
                        fc,
                        log_vars,
                        n_continuous=n_cont,
                        continuous_loss_weights=loss_weights,
                        candle_class_weights=candle_w,
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

    stopped_at = history[-1][0] if history else best_epoch
    print(f"Training finished at epoch {stopped_at}, best epoch {best_epoch}")

    return TrainingResult(
        best_val_loss=best_val,
        best_epoch=best_epoch,
        model_state=best_state,
        log_vars=best_log_vars,
        history=history,
        stopped_at_epoch=stopped_at,
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
        for batch in loader:
            xb = batch[0].to(device)
            xcat = batch[1].to(device)
            yb_z = batch[2]
            mb = batch[3]
            cont, *_ = model(xb, xcat)
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


def print_primary_metrics(metrics: Sequence[TargetMetrics]) -> None:
    """Highlight future_volatility correlation (primary export quality check)."""
    by_name = {m.name: m for m in metrics}
    vol_m = by_name.get("future_volatility")
    mfe_m = by_name.get("mfe")
    if vol_m is None:
        print("  future_volatility            (no valid samples)")
    else:
        print("Primary volatility correlation:")
        print(
            f"  {vol_m.name:28s}  corr={vol_m.corr:+.3f}  "
            f"MAE={vol_m.mae:.5f}  n={vol_m.n}"
        )
    if mfe_m is not None:
        print(
            f"  {mfe_m.name:28s}  corr={mfe_m.corr:+.3f}  "
            f"MAE={mfe_m.mae:.5f}  n={mfe_m.n}"
        )


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
        for batch in loader:
            xb = batch[0].to(device)
            xcat = batch[1].to(device)
            rb = batch[4]
            _, regime_logits, *_ = model(xb, xcat)
            pred_list.extend(torch.argmax(regime_logits, dim=1).cpu().numpy().tolist())
            true_list.extend(rb.numpy().tolist())
    return np.array(pred_list), np.array(true_list)


def evaluate_regime_accuracy(
    model: MarketTransformer,
    loader: DataLoader,
    *,
    device: torch.device,
) -> float:
    """Test-set accuracy for the volatility-regime classification head."""
    pred, true = evaluate_regime_head(model, loader, device=device)
    if len(true) == 0:
        return 0.0
    return float((pred == true).mean())


def evaluate_head_accuracy(
    model: MarketTransformer,
    loader: DataLoader,
    *,
    device: torch.device,
    output_index: int,
    target_index: int,
) -> float:
    """Accuracy for an auxiliary class head (1=regime, 2=structure, 3=candle)."""
    model.eval()
    pred_list: List[int] = []
    true_list: List[int] = []
    with torch.no_grad():
        for batch in loader:
            xb = batch[0].to(device)
            xcat = batch[1].to(device)
            target = batch[target_index]
            outputs = model(xb, xcat)
            logits = outputs[output_index]
            pred_list.extend(torch.argmax(logits, dim=1).cpu().numpy().tolist())
            true_list.extend(target.numpy().tolist())
    if not true_list:
        return 0.0
    pred = np.array(pred_list)
    true = np.array(true_list)
    return float((pred == true).mean())


@dataclass
class ExportQualityAssessment:
    """Tiered export quality result (sanity vs promotion-ready)."""

    tier: str
    checks: Dict[str, Any]
    warnings: List[str]
    disclaimer: str


def assess_export_quality(
    metrics: Sequence[TargetMetrics],
    *,
    resolution: str,
    min_vol_corr: float,
    regime_accuracy: float | None = None,
) -> ExportQualityAssessment:
    """Evaluate sanity and promotion tiers without blocking on promotion failures."""
    res = resolution.strip().lower()
    by_name = {m.name: m for m in metrics}
    vol_m = by_name.get("future_volatility")
    checks: Dict[str, Any] = {}
    warnings: List[str] = []

    if vol_m is None:
        return ExportQualityAssessment(
            tier="blocked",
            checks=checks,
            warnings=["no valid future_volatility test samples"],
            disclaimer=EXPORT_QUALITY_DISCLAIMER,
        )

    sanity_floor = float(min_vol_corr)
    promotion_vol_floor = float(PROMOTION_VOL_CORR)
    checks["future_volatility"] = {
        "corr": vol_m.corr,
        "sanity_floor": sanity_floor,
        "promotion_floor": promotion_vol_floor,
        "sanity_passed": vol_m.corr >= sanity_floor,
        "promotion_passed": vol_m.corr >= promotion_vol_floor,
    }
    if not checks["future_volatility"]["sanity_passed"]:
        return ExportQualityAssessment(
            tier="blocked",
            checks=checks,
            warnings=[
                f"future_volatility corr {vol_m.corr:.4f} < sanity floor {sanity_floor:.4f}"
            ],
            disclaimer=EXPORT_QUALITY_DISCLAIMER,
        )

    if regime_accuracy is not None:
        checks["regime_accuracy"] = {
            "value": float(regime_accuracy),
            "promotion_floor": PROMOTION_REGIME_ACCURACY,
            "promotion_passed": float(regime_accuracy) >= PROMOTION_REGIME_ACCURACY,
        }
        if not checks["regime_accuracy"]["promotion_passed"]:
            warnings.append(
                f"promotion: regime accuracy {regime_accuracy:.4f} "
                f"< {PROMOTION_REGIME_ACCURACY:.4f}"
            )

    if not checks["future_volatility"]["promotion_passed"]:
        warnings.append(
            f"promotion: future_volatility corr {vol_m.corr:.4f} "
            f"< {promotion_vol_floor:.4f}"
        )

    promotion_ready = (
        checks["future_volatility"]["promotion_passed"]
        and (
            regime_accuracy is None
            or checks.get("regime_accuracy", {}).get("promotion_passed", False)
        )
    )
    tier = "promotion_ready" if promotion_ready else "sanity_pass"
    return ExportQualityAssessment(
        tier=tier,
        checks=checks,
        warnings=warnings,
        disclaimer=EXPORT_QUALITY_DISCLAIMER,
    )


def check_export_quality_gate(
    metrics: Sequence[TargetMetrics],
    min_vol_corr: float,
) -> None:
    """Raise if future_volatility test correlation is below export floor."""
    assessment = assess_export_quality(
        metrics,
        resolution="15m",
        min_vol_corr=min_vol_corr,
    )
    if assessment.tier == "blocked":
        msg = assessment.warnings[0] if assessment.warnings else "export quality blocked"
        raise RuntimeError(f"Export blocked: {msg}")


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
    regime_accuracy: float | None = None,
    verify: bool = True,
    enforce_quality_gate: bool = True,
) -> Tuple[Path, Path, Path]:
    """Export ONNX + feature_config.json + metadata_transformer.json."""
    resolution = str(config.get("resolution") or "15m")
    min_corr = float(config.get("min_export_vol_corr") or 0.08)
    export_quality: Dict[str, Any] = {}
    if test_metrics is not None:
        assessment = assess_export_quality(
            test_metrics,
            resolution=resolution,
            min_vol_corr=min_corr,
            regime_accuracy=regime_accuracy,
        )
        export_quality = {
            "tier": assessment.tier,
            "checks": assessment.checks,
            "warnings": assessment.warnings,
            "disclaimer": assessment.disclaimer,
        }
        if assessment.warnings:
            for warning in assessment.warnings:
                print(f"Export quality warning: {warning}")
        print(f"Export quality tier: {assessment.tier}")
        if enforce_quality_gate and assessment.tier == "blocked":
            msg = assessment.warnings[0] if assessment.warnings else "quality gate failed"
            raise RuntimeError(f"Export blocked: {msg}")

    export_dir.mkdir(parents=True, exist_ok=True)
    onnx_name = onnx_filename_for_resolution(resolution)
    onnx_path = export_dir / onnx_name
    cfg_path = export_dir / TRANSFORMER_FEATURE_CONFIG_FILENAME
    meta_path = export_dir / TRANSFORMER_METADATA_FILENAME

    dummy_cont = torch.randn(1, window_len, n_features, device=device)
    dummy_cat = torch.zeros(1, window_len, dtype=torch.long, device=device)
    export_kwargs: Dict[str, Any] = {
        "input_names": ["continuous_features", "candle_class_ids"],
        "output_names": list(ONNX_OUTPUT_NAMES),
        "dynamic_axes": {
            "continuous_features": {0: "batch"},
            "candle_class_ids": {0: "batch"},
            "continuous_pred": {0: "batch"},
            "regime_logits": {0: "batch"},
            "structure_outcome_logits": {0: "batch"},
            "future_candle_logits": {0: "batch"},
        },
        "opset_version": 17,
        "export_params": True,
    }
    dummy_inputs = (dummy_cont, dummy_cat)
    try:
        torch.onnx.export(
            model,
            dummy_inputs,
            str(onnx_path),
            dynamo=False,
            **export_kwargs,
        )
    except TypeError:
        torch.onnx.export(model, dummy_inputs, str(onnx_path), **export_kwargs)

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
        onnx_outs = sess.run(
            None,
            {
                "continuous_features": dummy_cont.cpu().numpy(),
                "candle_class_ids": dummy_cat.cpu().numpy(),
            },
        )
        with torch.no_grad():
            torch_outs = model(dummy_cont, dummy_cat)
        for name, onnx_arr, torch_t in zip(ONNX_OUTPUT_NAMES, onnx_outs, torch_outs):
            diff = np.abs(onnx_arr - torch_t.cpu().numpy()).max()
            print(f"ONNX verify {name} max diff: {diff:.2e} shape={onnx_arr.shape}")

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
        export_quality=export_quality or None,
    )
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return onnx_path, cfg_path, meta_path
