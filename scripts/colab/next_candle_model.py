"""v8 multi-horizon 5m Transformer (research Colab; not the v6 path trainer)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset

from feature_store.transformer_btcusd.contract import (
    CANDLE_CLASS_CARDINALITY,
    CANDLE_EMBED_DIM,
    N_HORIZONS,
    NEXT_DIRECTION_CARDINALITY,
    STRUCTURE_OUTCOME_CARDINALITY,
    V8_CONTINUOUS_LABEL_COLS,
    V8_STRUCTURE_LOSS_WEIGHTS,
    VOLUME_STATE_CARDINALITY,
)
from feature_store.transformer_btcusd.inference import zscore_window


class NextCandleDataset(Dataset):
    """Windows of continuous features + candle ids with v8 horizon labels."""

    def __init__(
        self,
        x: np.ndarray,
        x_cat: np.ndarray,
        y_path: np.ndarray,
        path_mask: np.ndarray,
        volume_state: np.ndarray,
        horizon_dirs: np.ndarray,
        horizon_structs: np.ndarray,
        *,
        per_window_zscore: bool = False,
    ) -> None:
        self.x = x.astype(np.float32)
        self.x_cat = x_cat.astype(np.int64)
        self.y_path = y_path.astype(np.float32)
        self.path_mask = path_mask.astype(np.float32)
        self.volume_state = volume_state.astype(np.int64)
        self.horizon_dirs = horizon_dirs.astype(np.int64)
        self.horizon_structs = horizon_structs.astype(np.int64)
        self.per_window_zscore = bool(per_window_zscore)

    def __len__(self) -> int:
        return int(len(self.x))

    def __getitem__(self, i: int) -> Tuple[torch.Tensor, ...]:
        window = self.x[i]
        if self.per_window_zscore:
            window = zscore_window(window)
        return (
            torch.tensor(window, dtype=torch.float32),
            torch.tensor(self.x_cat[i], dtype=torch.long),
            torch.tensor(self.y_path[i], dtype=torch.float32),
            torch.tensor(self.path_mask[i], dtype=torch.float32),
            torch.tensor(self.volume_state[i], dtype=torch.long),
            torch.tensor(self.horizon_dirs[i], dtype=torch.long),
            torch.tensor(self.horizon_structs[i], dtype=torch.long),
        )


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 512) -> None:
        super().__init__()
        self.pe = nn.Parameter(torch.randn(1, max_len, d_model) * 0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1), :]


class NextCandleTransformer(nn.Module):
    """Shared encoder with per-horizon direction, structure, and path heads."""

    def __init__(
        self,
        n_features: int,
        d_model: int,
        nhead: int,
        num_layers: int,
        dropout: float,
        max_len: int,
        n_continuous: int,
        n_horizons: int = N_HORIZONS,
        candle_embed_dim: int = CANDLE_EMBED_DIM,
    ) -> None:
        super().__init__()
        self.n_horizons = int(n_horizons)
        self.candle_embed = nn.Embedding(CANDLE_CLASS_CARDINALITY, candle_embed_dim)
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
        shared_dim = max(d_model // 2, 16)
        self.shared = nn.Sequential(
            nn.Linear(d_model, shared_dim),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.dir_heads = nn.ModuleList(
            [
                nn.Linear(shared_dim, NEXT_DIRECTION_CARDINALITY)
                for _ in range(self.n_horizons)
            ]
        )
        self.structure_heads = nn.ModuleList(
            [
                nn.Linear(shared_dim, STRUCTURE_OUTCOME_CARDINALITY)
                for _ in range(self.n_horizons)
            ]
        )
        self.continuous_head = nn.Linear(shared_dim, n_continuous)
        self.volume_state_head = nn.Linear(shared_dim, VOLUME_STATE_CARDINALITY)

    def forward(
        self, x: torch.Tensor, candle_class_ids: torch.Tensor
    ) -> Tuple[torch.Tensor, ...]:
        embed = self.candle_embed(candle_class_ids)
        h = self.input_proj(torch.cat([x, embed], dim=-1))
        h = self.pos_enc(h)
        h = self.encoder(h)
        h = self.norm(h)
        shared = self.shared(h[:, -1, :])
        dir_outs = tuple(head(shared) for head in self.dir_heads)
        struct_outs = tuple(head(shared) for head in self.structure_heads)
        return (
            *dir_outs,
            *struct_outs,
            self.continuous_head(shared),
            self.volume_state_head(shared),
        )


def compute_v8_loss(
    outputs: Sequence[torch.Tensor],
    batch: Sequence[torch.Tensor],
    *,
    loss_weights: Dict[str, float] | None = None,
) -> torch.Tensor:
    """Per-horizon path MSE + direction/structure CE + volume CE."""
    weights = dict(V8_STRUCTURE_LOSS_WEIGHTS)
    if loss_weights:
        weights.update({str(k): float(v) for k, v in loss_weights.items()})
    (
        _xb,
        _xcat,
        y_path,
        path_mask,
        volume_y,
        horizon_dirs,
        horizon_structs,
    ) = batch
    n_h = int(horizon_dirs.size(1))
    dir_logits = outputs[:n_h]
    struct_logits = outputs[n_h : 2 * n_h]
    cont_pred = outputs[2 * n_h]
    vol_logits = outputs[2 * n_h + 1]

    def _ce_mean(logits: torch.Tensor, target: torch.Tensor, w: float) -> torch.Tensor:
        return w * nn.functional.cross_entropy(logits, target, reduction="mean")

    n_cont = min(
        cont_pred.size(1), y_path.size(1), len(V8_CONTINUOUS_LABEL_COLS)
    )
    path_diff = (cont_pred[:, :n_cont] - y_path[:, :n_cont]) ** 2
    masked = (path_diff * path_mask[:, :n_cont]).sum() / (
        path_mask[:, :n_cont].sum() + 1e-6
    )
    loss = float(weights["path"]) * masked
    loss = loss + _ce_mean(vol_logits, volume_y, float(weights["volume_state"]))

    dir_w = float(weights["direction"]) / max(n_h, 1)
    struct_w = float(weights["structure"]) / max(n_h, 1)
    for j in range(n_h):
        loss = loss + _ce_mean(dir_logits[j], horizon_dirs[:, j], dir_w)
        loss = loss + _ce_mean(struct_logits[j], horizon_structs[:, j], struct_w)
    return loss


def compute_v7_loss(
    outputs: Sequence[torch.Tensor],
    batch: Sequence[torch.Tensor],
    *,
    loss_weights: Dict[str, float] | None = None,
) -> torch.Tensor:
    """Alias kept so older notebook cells/tests can import a loss name."""
    return compute_v8_loss(outputs, batch, loss_weights=loss_weights)


def train_next_candle(
    model: NextCandleTransformer,
    train_loader: torch.utils.data.DataLoader,
    val_loader: torch.utils.data.DataLoader,
    *,
    device: torch.device,
    epochs: int,
    lr: float,
    weight_decay: float,
    patience: int,
    loss_weights: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    """Train with AdamW and early stopping on validation loss."""
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    best_val = float("inf")
    best_state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
    stale = 0
    history: List[Tuple[int, float, float]] = []
    aborted = False
    for epoch in range(int(epochs)):
        model.train()
        train_loss = 0.0
        n_train = 0
        for batch in train_loader:
            batch_d = tuple(t.to(device) for t in batch)
            opt.zero_grad(set_to_none=True)
            outs = model(batch_d[0], batch_d[1])
            loss = compute_v8_loss(outs, batch_d, loss_weights=loss_weights)
            loss_val = float(loss.detach().item())
            if not math.isfinite(loss_val):
                print(f"Non-finite train loss at epoch {epoch + 1} — aborting")
                aborted = True
                break
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            train_loss += loss_val
            n_train += 1
        if aborted:
            break
        if n_train == 0:
            print(f"No finite train batches at epoch {epoch + 1} — aborting")
            aborted = True
            break
        model.eval()
        val_loss = 0.0
        n_val = 0
        with torch.no_grad():
            for batch in val_loader:
                batch_d = tuple(t.to(device) for t in batch)
                outs = model(batch_d[0], batch_d[1])
                batch_val = float(
                    compute_v8_loss(outs, batch_d, loss_weights=loss_weights).item()
                )
                if not math.isfinite(batch_val):
                    print(f"Non-finite val loss at epoch {epoch + 1} — aborting")
                    aborted = True
                    break
                val_loss += batch_val
                n_val += 1
        if aborted:
            break
        train_loss /= max(n_train, 1)
        val_loss /= max(n_val, 1)
        history.append((epoch + 1, train_loss, val_loss))
        print(f"epoch {epoch + 1:03d}  train={train_loss:.4f}  val={val_loss:.4f}")
        if not math.isfinite(train_loss) or not math.isfinite(val_loss):
            print(f"Non-finite epoch loss at {epoch + 1} — aborting")
            aborted = True
            break
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
    epochs_ran = float(history[-1][0]) if history else 0.0
    ok = (not aborted) and math.isfinite(best_val) and bool(history)
    return {
        "ok": ok,
        "best_val_loss": float(best_val) if math.isfinite(best_val) else float("inf"),
        "epochs_ran": epochs_ran,
    }
