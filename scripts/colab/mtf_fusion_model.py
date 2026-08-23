"""Shared-encoder multi-TF fusion Transformer (v10).

One parameter set applied independently to 5m/10m/30m/1h/2h windows, softmax
fusion weights, four 3-class horizon heads. Cross-entropy only — no PnL loss.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset

from feature_store.transformer_btcusd.contract import (
    FUSION_DIRECTION_CARDINALITY,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_WINDOW_LEN,
    N_FUSION_HORIZONS,
)
from feature_store.transformer_btcusd.inference import zscore_window


def inverse_frequency_class_weights(
    class_ids: np.ndarray,
    n_classes: int,
) -> np.ndarray:
    """Inverse-frequency weights (mean-normalized) for imbalanced CE heads."""
    counts = np.bincount(
        np.asarray(class_ids, dtype=np.int64).ravel(), minlength=int(n_classes)
    ).astype(np.float64)
    counts = np.maximum(counts, 1.0)
    weights = 1.0 / counts
    weights = weights * (float(n_classes) / weights.sum())
    return weights.astype(np.float32)


class MtfFusionDataset(Dataset):
    """Per-sample dict of TF windows plus (n_horizons,) 3-class labels."""

    def __init__(
        self,
        windows: Dict[str, np.ndarray],
        labels: np.ndarray,
        *,
        per_window_zscore: bool = False,
    ) -> None:
        self.resolutions = tuple(FUSION_INPUT_RESOLUTIONS)
        n = None
        self.windows: Dict[str, np.ndarray] = {}
        for res in self.resolutions:
            arr = windows[res]
            if not isinstance(arr, np.ndarray) or arr.dtype != np.float32:
                arr = np.asarray(arr, dtype=np.float32)
            self.windows[res] = arr
            if n is None:
                n = len(arr)
            elif len(arr) != n:
                raise ValueError(f"Window length mismatch for {res}")
        self.labels = np.asarray(labels, dtype=np.int64)
        if n is None or len(self.labels) != n:
            raise ValueError("Labels length does not match windows")
        self.per_window_zscore = bool(per_window_zscore)

    def __len__(self) -> int:
        return int(len(self.labels))

    def __getitem__(self, i: int) -> Tuple[torch.Tensor, ...]:
        tensors: List[torch.Tensor] = []
        for res in self.resolutions:
            window = np.ascontiguousarray(self.windows[res][i], dtype=np.float32)
            if not window.flags.writeable:
                window = np.array(window, dtype=np.float32, copy=True)
            if self.per_window_zscore:
                window = zscore_window(window)
            tensors.append(torch.from_numpy(window))
        tensors.append(torch.as_tensor(self.labels[i], dtype=torch.long))
        return tuple(tensors)


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 512) -> None:
        super().__init__()
        self.pe = nn.Parameter(torch.randn(1, max_len, d_model) * 0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1), :]


class MtfFusionTransformer(nn.Module):
    """Shared encoder E, softmax TF weights, four independent 3-class heads."""

    def __init__(
        self,
        n_features: int,
        d_model: int = 64,
        nhead: int = 4,
        num_layers: int = 2,
        dropout: float = 0.15,
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
        h = self.pos_enc(h)
        h = self.encoder(h)
        h = self.norm(h)
        return h[:, -1, :]

    def fusion_weights(self) -> torch.Tensor:
        return torch.softmax(self.fusion_logits, dim=0)

    def forward(self, *tf_windows: torch.Tensor) -> Tuple[torch.Tensor, ...]:
        if len(tf_windows) != self.n_tfs:
            raise ValueError(
                f"Expected {self.n_tfs} TF windows, got {len(tf_windows)}"
            )
        zs = [self.encode_tf(tf_windows[i], i) for i in range(self.n_tfs)]
        stacked = torch.stack(zs, dim=1)
        weights = self.fusion_weights().view(1, self.n_tfs, 1)
        combined = (stacked * weights).sum(dim=1)
        shared = self.shared(combined)
        dir_outs = tuple(head(shared) for head in self.dir_heads)
        fusion_logits = self.fusion_logits.unsqueeze(0).expand(shared.size(0), -1)
        return (*dir_outs, fusion_logits)


def compute_fusion_loss(
    outputs: Sequence[torch.Tensor],
    labels: torch.Tensor,
    *,
    class_weights: Optional[torch.Tensor] = None,
) -> torch.Tensor:
    """Mean CE across the four horizon heads. Ignores labels < 0."""
    n_h = int(labels.size(1))
    loss = labels.new_zeros(())
    counted = 0
    for j in range(n_h):
        logits = outputs[j]
        target = labels[:, j]
        valid = target >= 0
        if not bool(valid.any()):
            continue
        loss = loss + nn.functional.cross_entropy(
            logits[valid],
            target[valid],
            weight=class_weights,
            reduction="mean",
        )
        counted += 1
    if counted == 0:
        return logits.sum() * 0.0
    return loss / float(counted)


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
) -> Dict[str, Any]:
    """AdamW + early stopping on validation CE. Never sees the test loader."""
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    best_val = float("inf")
    best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
    stale = 0
    history: List[Tuple[int, float, float]] = []
    aborted = False
    cw = class_weights.to(device) if class_weights is not None else None

    def _batch_loss(batch: Sequence[torch.Tensor]) -> torch.Tensor:
        windows = batch[:-1]
        labels = batch[-1]
        outs = model(*windows)
        return compute_fusion_loss(outs, labels, class_weights=cw)

    for epoch in range(int(epochs)):
        model.train()
        train_loss = 0.0
        n_train = 0
        for batch in train_loader:
            batch_d = tuple(t.to(device) for t in batch)
            opt.zero_grad(set_to_none=True)
            loss = _batch_loss(batch_d)
            loss_val = float(loss.detach().item())
            if not math.isfinite(loss_val):
                aborted = True
                break
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            train_loss += loss_val
            n_train += 1
        if aborted or n_train == 0:
            break
        model.eval()
        val_loss = 0.0
        n_val = 0
        with torch.no_grad():
            for batch in val_loader:
                batch_d = tuple(t.to(device) for t in batch)
                batch_val = float(_batch_loss(batch_d).item())
                if not math.isfinite(batch_val):
                    aborted = True
                    break
                val_loss += batch_val
                n_val += 1
        if aborted or n_val == 0:
            break
        train_loss /= max(n_train, 1)
        val_loss /= max(n_val, 1)
        history.append((epoch + 1, train_loss, val_loss))
        print(f"epoch {epoch + 1:03d}  train={train_loss:.4f}  val={val_loss:.4f}")
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
