"""Shared-encoder multi-TF fusion Transformer (v11).

One parameter set applied independently to 5m/10m/30m/1h/2h windows, softmax
fusion weights, three 2-class horizon heads. Cross-entropy only — no PnL loss.
NEUTRAL labels are ignore_index and never enter the loss.
"""

from __future__ import annotations

import contextlib
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset

from feature_store.transformer_btcusd.contract import (
    FUSION_DIRECTION_CARDINALITY,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_TARGET_WINDOW_MINUTES,
    FUSION_WINDOW_LEN,
    N_FUSION_HORIZONS,
    RESOLUTION_MINUTES,
    resolve_fusion_window_lens,
)
from feature_store.transformer_btcusd.inference import zscore_window


def inverse_frequency_class_weights(
    class_ids: np.ndarray,
    n_classes: int,
) -> np.ndarray:
    """Inverse-frequency weights (mean-normalized) for imbalanced CE heads.

    Ignored labels (< 0) are excluded. Empty class counts are clipped to 1.
    """
    ids = np.asarray(class_ids, dtype=np.int64).ravel()
    ids = ids[ids >= 0]
    if ids.size == 0:
        return np.ones(int(n_classes), dtype=np.float32)
    counts = np.bincount(ids, minlength=int(n_classes)).astype(np.float64)
    counts = np.maximum(counts, 1.0)
    weights = 1.0 / counts
    weights = weights * (float(n_classes) / weights.sum())
    return weights.astype(np.float32)


WindowArray = Union[np.ndarray, torch.Tensor]


def _ndarray_to_tensor(array: np.ndarray, dtype: torch.dtype) -> torch.Tensor:
    """Zero-copy from_numpy when the torch/numpy bridge works; else copy."""
    try:
        if dtype == torch.float32 and array.dtype == np.float32:
            return torch.from_numpy(array)
        return torch.as_tensor(array, dtype=dtype)
    except RuntimeError:
        return torch.tensor(np.asarray(array), dtype=dtype)


def _window_row_to_tensor(window: WindowArray) -> torch.Tensor:
    """One host tensor for a (time, feat) row. Copies memmap slices once."""
    if isinstance(window, torch.Tensor):
        row = window.detach()
        if row.dtype != torch.float32:
            row = row.to(dtype=torch.float32)
        return row if row.is_contiguous() else row.contiguous()
    arr = np.asarray(window)
    if arr.dtype != np.float32 or not arr.flags.c_contiguous or not arr.flags.writeable:
        arr = np.array(arr, dtype=np.float32, copy=True, order="C")
    return _ndarray_to_tensor(arr, torch.float32)


class MtfFusionDataset(Dataset):
    """Per-sample TF windows plus (n_horizons,) 2-class labels.

    Accepts numpy memmaps or CPU float32 tensors. Tensor storage avoids a
    numpy copy on each ``__getitem__`` when windows fit in RAM.
    """

    def __init__(
        self,
        windows: Mapping[str, WindowArray],
        labels: Union[np.ndarray, torch.Tensor],
        *,
        per_window_zscore: bool = False,
    ) -> None:
        self.resolutions = tuple(FUSION_INPUT_RESOLUTIONS)
        n = None
        self.windows: Dict[str, WindowArray] = {}
        for res in self.resolutions:
            arr = windows[res]
            if isinstance(arr, torch.Tensor):
                stored: WindowArray = arr.detach()
                if stored.dtype != torch.float32:
                    stored = stored.to(dtype=torch.float32)
                if not stored.is_contiguous():
                    stored = stored.contiguous()
                n_i = int(stored.shape[0])
            else:
                stored = arr
                if not isinstance(stored, np.ndarray) or stored.dtype != np.float32:
                    stored = np.asarray(arr, dtype=np.float32)
                n_i = int(len(stored))
            self.windows[res] = stored
            if n is None:
                n = n_i
            elif n_i != n:
                raise ValueError(f"Window length mismatch for {res}")
        if isinstance(labels, torch.Tensor):
            self.labels: WindowArray = labels.detach().to(dtype=torch.long)
            n_y = int(self.labels.shape[0])
        else:
            self.labels = np.asarray(labels, dtype=np.int64)
            n_y = int(len(self.labels))
        if n is None or n_y != n:
            raise ValueError("Labels length does not match windows")
        self.per_window_zscore = bool(per_window_zscore)

    def __len__(self) -> int:
        return int(len(self.labels))

    def __getitem__(self, i: int) -> Tuple[torch.Tensor, ...]:
        tensors: List[torch.Tensor] = []
        for res in self.resolutions:
            window = self.windows[res][i]
            if self.per_window_zscore and not isinstance(window, torch.Tensor):
                window = zscore_window(np.asarray(window, dtype=np.float32))
            tensors.append(_window_row_to_tensor(window))
        label_row = self.labels[i]
        if isinstance(label_row, torch.Tensor):
            tensors.append(label_row.to(dtype=torch.long))
        else:
            tensors.append(_ndarray_to_tensor(np.asarray(label_row), torch.long))
        return tuple(tensors)


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 512) -> None:
        super().__init__()
        self.pe = nn.Parameter(torch.randn(1, max_len, d_model) * 0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1), :]


class MtfFusionTransformer(nn.Module):
    """Shared encoder E, softmax TF weights, three independent 2-class heads."""

    def __init__(
        self,
        n_features: int,
        d_model: int = 64,
        nhead: int = 4,
        num_layers: int = 2,
        dropout: float = 0.30,
        max_len: int = FUSION_WINDOW_LEN,
        n_tfs: int = 5,
        n_horizons: int = N_FUSION_HORIZONS,
        n_classes: int = FUSION_DIRECTION_CARDINALITY,
    ) -> None:
        super().__init__()
        self.n_tfs = int(n_tfs)
        self.n_horizons = int(n_horizons)
        self.n_classes = int(n_classes)
        self.tf_embed = nn.Embedding(self.n_tfs, d_model)
        self.input_proj = nn.Linear(n_features, d_model)
        self.scale_proj = nn.Linear(1, d_model, bias=False)
        scale_vals = [
            math.log(float(RESOLUTION_MINUTES[res])) / math.log(120.0)
            for res in FUSION_INPUT_RESOLUTIONS[: self.n_tfs]
        ]
        self.register_buffer(
            "tf_bar_scale", torch.tensor(scale_vals, dtype=torch.float32)
        )
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
        self.fusion_logits = nn.Parameter(torch.zeros(self.n_tfs))
        shared_dim = max(d_model // 2, 16)
        self.shared = nn.Sequential(
            nn.Linear(d_model, shared_dim),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.dir_heads = nn.ModuleList(
            [nn.Linear(shared_dim, self.n_classes) for _ in range(self.n_horizons)]
        )

    def encode_tf(self, x: torch.Tensor, tf_index: int) -> torch.Tensor:
        """Encode one TF window (batch, time, feat) → (batch, d_model)."""
        h = self.input_proj(x)
        tf_ids = torch.full(
            (x.size(0), x.size(1)),
            int(tf_index),
            device=x.device,
            dtype=torch.long,
        )
        h = h + self.tf_embed(tf_ids)
        scale = self.tf_bar_scale[int(tf_index)].to(dtype=h.dtype)
        scale = scale.view(1, 1, 1).expand(x.size(0), x.size(1), 1)
        h = h + self.scale_proj(scale)
        h = self.pos_enc(h)
        h = self.encoder(h)
        h = self.norm(h)
        return h[:, -1, :]

    def encode_all_tfs(self, tf_windows: Sequence[torch.Tensor]) -> torch.Tensor:
        """Encode every TF at its native length. Returns (batch, n_tf, d_model)."""
        if len(tf_windows) != self.n_tfs:
            raise ValueError(
                f"Expected {self.n_tfs} TF windows, got {len(tf_windows)}"
            )
        encoded = [
            self.encode_tf(window, i) for i, window in enumerate(tf_windows)
        ]
        return torch.stack(encoded, dim=1)

    def fusion_weights(self) -> torch.Tensor:
        return torch.softmax(self.fusion_logits, dim=0)

    def forward(self, *tf_windows: torch.Tensor) -> Tuple[torch.Tensor, ...]:
        if len(tf_windows) != self.n_tfs:
            raise ValueError(
                f"Expected {self.n_tfs} TF windows, got {len(tf_windows)}"
            )
        stacked = self.encode_all_tfs(tf_windows)
        weights = self.fusion_weights().view(1, self.n_tfs, 1)
        combined = (stacked * weights).sum(dim=1)
        shared = self.shared(combined)
        dir_outs = tuple(head(shared) for head in self.dir_heads)
        fusion_logits = self.fusion_logits.unsqueeze(0).expand(shared.size(0), -1)
        return (*dir_outs, fusion_logits)


def fusion_model_from_config(
    n_features: int,
    config: Mapping[str, Any],
) -> MtfFusionTransformer:
    """Build the fused transformer from a training CONFIG mapping."""
    target = int(config.get("target_window_minutes") or FUSION_TARGET_WINDOW_MINUTES)
    lens = resolve_fusion_window_lens(
        config.get("window_lens"),
        config.get("window_len"),
        target_minutes=target,
    )
    max_len = max(int(v) for v in lens.values())
    return MtfFusionTransformer(
        n_features=int(n_features),
        d_model=int(config.get("d_model") or 64),
        nhead=int(config.get("nhead") or 4),
        num_layers=int(config.get("num_layers") or 2),
        dropout=float(config.get("dropout") or 0.30),
        max_len=max_len,
    )


def compute_fusion_loss(
    outputs: Sequence[torch.Tensor],
    labels: torch.Tensor,
    *,
    class_weights: Optional[torch.Tensor] = None,
    label_smoothing: float = 0.0,
    horizon_weights: Optional[Sequence[float]] = None,
) -> torch.Tensor:
    """Weighted mean CE across 2-class horizon heads. Ignores labels < 0."""
    n_h = int(labels.size(1))
    loss = torch.zeros((), device=labels.device, dtype=torch.float32)
    weight_sum = 0.0
    last_logits = outputs[0]
    smooth = float(label_smoothing)
    for j in range(n_h):
        logits = outputs[j]
        last_logits = logits
        target = labels[:, j]
        valid = target >= 0
        if not bool(valid.any()):
            continue
        head_w = 1.0
        if horizon_weights is not None and j < len(horizon_weights):
            head_w = float(horizon_weights[j])
        if head_w <= 0.0:
            continue
        loss = loss + head_w * nn.functional.cross_entropy(
            logits[valid],
            target[valid],
            weight=class_weights,
            reduction="mean",
            label_smoothing=smooth,
        )
        weight_sum += head_w
    if weight_sum <= 0.0:
        return last_logits.sum() * 0.0
    return loss / float(weight_sum)


def train_mtf_fusion(
    model: MtfFusionTransformer,
    train_loader: torch.utils.data.DataLoader,
    val_loader: torch.utils.data.DataLoader,
    *,
    device: torch.device,
    epochs: int,
    lr: float,
    weight_decay: float,
    patience: int,
    class_weights: Optional[torch.Tensor] = None,
    label_smoothing: float = 0.0,
    horizon_weights: Optional[Sequence[float]] = None,
    lr_schedule: str = "constant",
    amp: bool = False,
) -> Dict[str, Any]:
    """AdamW + early stopping on validation CE. Never sees the test loader."""
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = None
    if str(lr_schedule).lower() == "cosine":
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            opt, T_max=max(int(epochs), 1)
        )
    best_val = float("inf")
    best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
    stale = 0
    history: List[Tuple[int, float, float]] = []
    aborted = False
    cw = class_weights.to(device) if class_weights is not None else None
    hw: Optional[Sequence[float]] = None
    if horizon_weights is not None:
        hw = [float(x) for x in horizon_weights]
    use_amp = bool(amp) and device.type == "cuda"
    non_blocking = device.type == "cuda"
    if device.type == "cuda":
        torch.backends.cudnn.benchmark = True
    scaler: Any = None
    if use_amp:
        try:
            scaler = torch.amp.GradScaler("cuda")
        except (TypeError, AttributeError):
            scaler = torch.cuda.amp.GradScaler()

    def _autocast() -> Any:
        if not use_amp:
            return contextlib.nullcontext()
        try:
            return torch.autocast(device_type="cuda")
        except TypeError:
            return torch.cuda.amp.autocast()

    def _batch_loss(batch: Sequence[torch.Tensor]) -> torch.Tensor:
        windows = batch[:-1]
        labels = batch[-1]
        outs = model(*windows)
        return compute_fusion_loss(
            outs,
            labels,
            class_weights=cw,
            label_smoothing=float(label_smoothing),
            horizon_weights=hw,
        )

    def _move(batch: Sequence[torch.Tensor]) -> Tuple[torch.Tensor, ...]:
        return tuple(t.to(device, non_blocking=non_blocking) for t in batch)

    for epoch in range(int(epochs)):
        model.train()
        train_sum: Optional[torch.Tensor] = None
        n_train = 0
        for batch in train_loader:
            batch_d = _move(batch)
            opt.zero_grad(set_to_none=True)
            with _autocast():
                loss = _batch_loss(batch_d)
            if scaler is not None:
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(opt)
                scaler.update()
            else:
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
            detached = loss.detach().float()
            train_sum = detached if train_sum is None else train_sum + detached
            n_train += 1
        if n_train == 0:
            aborted = True
            break
        train_loss = float((train_sum / n_train).item())
        if not math.isfinite(train_loss):
            aborted = True
            break
        model.eval()
        val_sum: Optional[torch.Tensor] = None
        n_val = 0
        with torch.no_grad():
            for batch in val_loader:
                batch_d = _move(batch)
                with _autocast():
                    batch_loss = _batch_loss(batch_d).float()
                val_sum = batch_loss if val_sum is None else val_sum + batch_loss
                n_val += 1
        if n_val == 0:
            aborted = True
            break
        val_loss = float((val_sum / n_val).item())
        if not math.isfinite(val_loss):
            aborted = True
            break
        history.append((epoch + 1, train_loss, val_loss))
        print(f"epoch {epoch + 1:03d}  train={train_loss:.4f}  val={val_loss:.4f}")
        if scheduler is not None:
            scheduler.step()
        if val_loss < best_val:
            best_val = val_loss
            stale = 0
            best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
        else:
            stale += 1
            if stale >= int(patience):
                print(f"Early stopping at epoch {epoch + 1}")
                break
    model.load_state_dict(best_state)
    ok = (not aborted) and math.isfinite(best_val) and bool(history)
    return {
        "ok": ok,
        "best_val_loss": float(best_val) if math.isfinite(best_val) else float("inf"),
        "epochs_ran": float(history[-1][0]) if history else 0.0,
        "history": history,
    }
