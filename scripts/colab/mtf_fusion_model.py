"""Shared-encoder multi-TF fusion Transformer (v15 research).

One parameter set applied independently to 5m/10m/30m/1h/2h windows, softmax
fusion weights, four 3-class direction heads (10m/15m/30m/1h) plus per-horizon
ret and side-aware long/short MFE/MAE. Optional candle/chart embeddings. Live
v11 remains 2-class ignore_index NEUTRAL in FusionModelNode.
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
    CANDLE_CLASS_CARDINALITY,
    CANDLE_EMBED_DIM,
    CHART_EMBED_DIM,
    CHART_PATTERN_CARDINALITY,
    FUSION_INPUT_RESOLUTIONS,
    FUSION_TARGET_WINDOW_MINUTES,
    FUSION_WINDOW_LEN,
    LABEL_V2_DIRECTION_CARDINALITY,
    LABEL_V2_HORIZON_KEYS,
    LABEL_V2_PATH_LOSS_WEIGHTS,
    LABEL_V2_REG_FIELDS,
    N_FUSION_HORIZONS,
    RESOLUTION_MINUTES,
    resolve_fusion_window_lens,
)
from feature_store.transformer_btcusd.inference import zscore_window


class FusionTrainLabels:
    """Direction (n, H) int64 plus path (n, H, F) float32 aligned on samples."""

    __slots__ = ("direction", "path")

    def __init__(self, direction: np.ndarray, path: np.ndarray) -> None:
        self.direction = np.asarray(direction, dtype=np.int64)
        self.path = np.asarray(path, dtype=np.float32)
        if int(self.direction.shape[0]) != int(self.path.shape[0]):
            raise ValueError("direction/path length mismatch")

    def __len__(self) -> int:
        return int(self.direction.shape[0])

    def __getitem__(self, sl: Any) -> "FusionTrainLabels":
        return FusionTrainLabels(self.direction[sl], self.path[sl])


def _direction_array(class_ids: Any) -> np.ndarray:
    if isinstance(class_ids, FusionTrainLabels):
        return np.asarray(class_ids.direction, dtype=np.int64)
    return np.asarray(class_ids, dtype=np.int64)


def inverse_frequency_class_weights(
    class_ids: np.ndarray,
    n_classes: int,
) -> np.ndarray:
    """Inverse-frequency weights (mean-normalized) for imbalanced CE heads.

    Ignored labels (< 0) are excluded. Empty class counts are clipped to 1.
    """
    ids = _direction_array(class_ids).ravel()
    ids = ids[ids >= 0]
    if ids.size == 0:
        return np.ones(int(n_classes), dtype=np.float32)
    counts = np.bincount(ids, minlength=int(n_classes)).astype(np.float64)
    counts = np.maximum(counts, 1.0)
    weights = 1.0 / counts
    weights = weights * (float(n_classes) / weights.sum())
    return weights.astype(np.float32)


def resolve_fusion_class_weights(
    class_ids: Any,
    n_classes: int,
    config: Optional[Mapping[str, Any]] = None,
) -> Optional[np.ndarray]:
    """Inverse-frequency CE weights, or None when ``use_class_weights`` is False."""
    if config is not None and not bool(config.get("use_class_weights", True)):
        return None
    return inverse_frequency_class_weights(class_ids, n_classes)


def fusion_class_weight_tensor(
    class_ids: Any,
    n_classes: int,
    config: Optional[Mapping[str, Any]] = None,
) -> Optional[torch.Tensor]:
    """Host float32 class-weight tensor, or None for uniform CE."""
    weights = resolve_fusion_class_weights(class_ids, n_classes, config)
    if weights is None:
        return None
    return torch.tensor(weights, dtype=torch.float32)


WindowArray = Union[np.ndarray, torch.Tensor]


def _ndarray_to_tensor(array: np.ndarray, dtype: torch.dtype) -> torch.Tensor:
    """Zero-copy from_numpy when the torch/numpy bridge works; else copy."""
    try:
        if dtype == torch.float32 and array.dtype == np.float32:
            return torch.from_numpy(array)
        return torch.as_tensor(array, dtype=dtype)
    except RuntimeError:
        return torch.tensor(np.asarray(array), dtype=dtype)


def tensor_to_numpy(tensor: torch.Tensor) -> np.ndarray:
    """Host ndarray. Copies via Python when the torch/numpy C API is broken."""
    host = tensor.detach().cpu().contiguous()
    try:
        return host.numpy()
    except RuntimeError:
        np_dtype: Any = None
        if host.dtype == torch.float32:
            np_dtype = np.float32
        elif host.dtype == torch.float64:
            np_dtype = np.float64
        elif host.dtype == torch.int64:
            np_dtype = np.int64
        elif host.dtype == torch.int32:
            np_dtype = np.int32
        arr = np.array(host.tolist())
        if np_dtype is not None:
            return arr.astype(np_dtype, copy=False)
        return arr


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


def _id_row_to_tensor(window: WindowArray) -> torch.Tensor:
    """One host int64 tensor for a (time,) id row."""
    if isinstance(window, torch.Tensor):
        row = window.detach()
        if row.dtype != torch.long:
            row = row.to(dtype=torch.long)
        return row if row.is_contiguous() else row.contiguous()
    arr = np.asarray(window)
    if arr.dtype != np.int64 or not arr.flags.c_contiguous:
        arr = np.array(arr, dtype=np.int64, copy=True, order="C")
    return _ndarray_to_tensor(arr, torch.long)


class MtfFusionDataset(Dataset):
    """Per-sample TF windows plus direction labels and optional path targets.

    Accepts numpy memmaps or CPU float32 tensors. Tensor storage avoids a
    numpy copy on each ``__getitem__`` when windows fit in RAM. Optional
    candle/chart id windows are int64 and never z-scored.
    """

    def __init__(
        self,
        windows: Mapping[str, WindowArray],
        labels: Union[np.ndarray, torch.Tensor, FusionTrainLabels],
        *,
        path_labels: Optional[Union[np.ndarray, torch.Tensor]] = None,
        per_window_zscore: bool = False,
        candle_ids: Optional[Mapping[str, WindowArray]] = None,
        chart_ids: Optional[Mapping[str, WindowArray]] = None,
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
        self.candle_ids: Optional[Dict[str, WindowArray]] = None
        self.chart_ids: Optional[Dict[str, WindowArray]] = None
        if candle_ids is not None or chart_ids is not None:
            if candle_ids is None or chart_ids is None:
                raise ValueError("candle_ids and chart_ids must be provided together")
            self.candle_ids = {}
            self.chart_ids = {}
            for res in self.resolutions:
                cdl = _store_id_array(candle_ids[res], n=int(n or 0), name=f"candle {res}")
                chp = _store_id_array(chart_ids[res], n=int(n or 0), name=f"chart {res}")
                self.candle_ids[res] = cdl
                self.chart_ids[res] = chp
        path_src: Optional[Union[np.ndarray, torch.Tensor]] = path_labels
        if isinstance(labels, FusionTrainLabels):
            dir_src: Union[np.ndarray, torch.Tensor] = labels.direction
            path_src = labels.path if path_src is None else path_src
        else:
            dir_src = labels
        if isinstance(dir_src, torch.Tensor):
            self.labels: WindowArray = dir_src.detach().to(dtype=torch.long)
            n_y = int(self.labels.shape[0])
        else:
            self.labels = np.asarray(dir_src, dtype=np.int64)
            n_y = int(len(self.labels))
        self.path_labels: Optional[WindowArray] = None
        if path_src is not None:
            if isinstance(path_src, torch.Tensor):
                self.path_labels = path_src.detach().to(dtype=torch.float32)
                n_p = int(self.path_labels.shape[0])
            else:
                self.path_labels = np.asarray(path_src, dtype=np.float32)
                n_p = int(len(self.path_labels))
            if n_p != n_y:
                raise ValueError("Path labels length does not match direction labels")
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
        if self.candle_ids is not None and self.chart_ids is not None:
            for res in self.resolutions:
                tensors.append(_id_row_to_tensor(self.candle_ids[res][i]))
            for res in self.resolutions:
                tensors.append(_id_row_to_tensor(self.chart_ids[res][i]))
        label_row = self.labels[i]
        if isinstance(label_row, torch.Tensor):
            tensors.append(label_row.to(dtype=torch.long))
        else:
            tensors.append(_ndarray_to_tensor(np.asarray(label_row), torch.long))
        if self.path_labels is not None:
            path_row = self.path_labels[i]
            if isinstance(path_row, torch.Tensor):
                tensors.append(path_row.to(dtype=torch.float32))
            else:
                tensors.append(
                    _ndarray_to_tensor(np.asarray(path_row, dtype=np.float32), torch.float32)
                )
        return tuple(tensors)


def _store_id_array(arr: WindowArray, *, n: int, name: str) -> WindowArray:
    if isinstance(arr, torch.Tensor):
        stored = arr.detach()
        if stored.dtype != torch.long:
            stored = stored.to(dtype=torch.long)
        if not stored.is_contiguous():
            stored = stored.contiguous()
        n_i = int(stored.shape[0])
    else:
        stored = arr
        if not isinstance(stored, np.ndarray) or stored.dtype != np.int64:
            stored = np.asarray(arr, dtype=np.int64)
        n_i = int(len(stored))
    if n_i != n:
        raise ValueError(f"{name} length {n_i} != {n}")
    return stored


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 512) -> None:
        super().__init__()
        self.pe = nn.Parameter(torch.randn(1, max_len, d_model) * 0.02)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1), :]


class MtfFusionTransformer(nn.Module):
    """Shared encoder E, softmax TF weights, 3-class dir + path heads."""

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
        n_classes: int = LABEL_V2_DIRECTION_CARDINALITY,
        use_state_embeddings: bool = False,
        candle_embed_dim: int = CANDLE_EMBED_DIM,
        chart_embed_dim: int = CHART_EMBED_DIM,
    ) -> None:
        super().__init__()
        self.n_tfs = int(n_tfs)
        self.n_horizons = int(n_horizons)
        self.n_classes = int(n_classes)
        self.n_path_fields = len(LABEL_V2_REG_FIELDS)
        self.n_features = int(n_features)
        self.use_state_embeddings = bool(use_state_embeddings)
        self.zero_candle_embed = False
        self.zero_chart_embed = False
        self.tf_embed = nn.Embedding(self.n_tfs, d_model)
        proj_in = int(n_features)
        if self.use_state_embeddings:
            self.candle_embed: Optional[nn.Embedding] = nn.Embedding(
                CANDLE_CLASS_CARDINALITY, int(candle_embed_dim)
            )
            self.chart_embed: Optional[nn.Embedding] = nn.Embedding(
                CHART_PATTERN_CARDINALITY, int(chart_embed_dim)
            )
            proj_in = int(n_features) + int(candle_embed_dim) + int(chart_embed_dim)
        else:
            self.candle_embed = None
            self.chart_embed = None
        self.input_proj = nn.Linear(proj_in, d_model)
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
        self.path_heads = nn.ModuleList(
            [nn.Linear(shared_dim, self.n_path_fields) for _ in range(self.n_horizons)]
        )

    def encode_tf(
        self,
        x: torch.Tensor,
        tf_index: int,
        candle_ids: Optional[torch.Tensor] = None,
        chart_ids: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """Encode one TF window (batch, time, feat) → (batch, d_model)."""
        if self.use_state_embeddings:
            if self.candle_embed is None or self.chart_embed is None:
                raise RuntimeError("state embeddings are enabled but missing")
            if candle_ids is None or chart_ids is None:
                raise ValueError("candle_ids and chart_ids are required")
            cdl = self.candle_embed(candle_ids.long())
            chp = self.chart_embed(chart_ids.long())
            if self.zero_candle_embed:
                cdl = torch.zeros_like(cdl)
            if self.zero_chart_embed:
                chp = torch.zeros_like(chp)
            x = torch.cat([x, cdl, chp], dim=-1)
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

    def encode_all_tfs(
        self,
        tf_windows: Sequence[torch.Tensor],
        candle_ids: Optional[Sequence[torch.Tensor]] = None,
        chart_ids: Optional[Sequence[torch.Tensor]] = None,
    ) -> torch.Tensor:
        """Encode every TF at its native length. Returns (batch, n_tf, d_model)."""
        if len(tf_windows) != self.n_tfs:
            raise ValueError(
                f"Expected {self.n_tfs} TF windows, got {len(tf_windows)}"
            )
        encoded = [
            self.encode_tf(
                window,
                i,
                candle_ids=None if candle_ids is None else candle_ids[i],
                chart_ids=None if chart_ids is None else chart_ids[i],
            )
            for i, window in enumerate(tf_windows)
        ]
        return torch.stack(encoded, dim=1)

    def fusion_weights(self) -> torch.Tensor:
        return torch.softmax(self.fusion_logits, dim=0)

    def forward(self, *tf_windows: torch.Tensor) -> Tuple[torch.Tensor, ...]:
        n = self.n_tfs
        if len(tf_windows) == n:
            stacked = self.encode_all_tfs(tf_windows)
        elif len(tf_windows) == 3 * n:
            xs = tf_windows[:n]
            cdl = tf_windows[n : 2 * n]
            chp = tf_windows[2 * n : 3 * n]
            stacked = self.encode_all_tfs(xs, candle_ids=cdl, chart_ids=chp)
        else:
            raise ValueError(
                f"Expected {n} or {3 * n} TF tensors, got {len(tf_windows)}"
            )
        weights = self.fusion_weights().view(1, self.n_tfs, 1)
        combined = (stacked * weights).sum(dim=1)
        shared = self.shared(combined)
        dir_outs = tuple(head(shared) for head in self.dir_heads)
        path_vecs = [head(shared) for head in self.path_heads]
        path_outs = tuple(
            vec[:, k : k + 1] for vec in path_vecs for k in range(self.n_path_fields)
        )
        fusion_logits = self.fusion_logits.unsqueeze(0).expand(shared.size(0), -1)
        return (*dir_outs, *path_outs, fusion_logits)


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
    n_horizons = len(config.get("horizon_keys") or LABEL_V2_HORIZON_KEYS)
    return MtfFusionTransformer(
        n_features=int(n_features),
        d_model=int(config.get("d_model") or 64),
        nhead=int(config.get("nhead") or 4),
        num_layers=int(config.get("num_layers") or 2),
        dropout=float(config.get("dropout") or 0.30),
        max_len=max_len,
        n_horizons=n_horizons,
        n_classes=int(config.get("n_classes") or LABEL_V2_DIRECTION_CARDINALITY),
        use_state_embeddings=bool(config.get("use_state_embeddings", False)),
    )


def _as_col(tensor: torch.Tensor) -> torch.Tensor:
    if tensor.ndim == 1:
        return tensor.unsqueeze(-1)
    return tensor


def unpack_fusion_batch(
    batch: Sequence[torch.Tensor],
) -> Tuple[Tuple[torch.Tensor, ...], torch.Tensor, Optional[torch.Tensor]]:
    """Split TF windows from y_dir and optional y_reg (last tensor if float)."""
    if len(batch) < 2:
        raise ValueError("fusion batch must include windows and labels")
    if batch[-1].is_floating_point():
        return tuple(batch[:-2]), batch[-2], batch[-1]
    return tuple(batch[:-1]), batch[-1], None


def compute_fusion_loss(
    outputs: Sequence[torch.Tensor],
    labels: torch.Tensor,
    *,
    path_labels: Optional[torch.Tensor] = None,
    class_weights: Optional[torch.Tensor] = None,
    label_smoothing: float = 0.0,
    horizon_weights: Optional[Sequence[float]] = None,
    path_task_weights: Optional[Mapping[str, float]] = None,
) -> torch.Tensor:
    """3-class CE (trains NEUTRAL) plus SmoothL1 on finite path fields."""
    n_h = int(labels.size(1))
    n_f = len(LABEL_V2_REG_FIELDS)
    weights = dict(LABEL_V2_PATH_LOSS_WEIGHTS)
    if path_task_weights is not None:
        weights.update({str(k): float(v) for k, v in path_task_weights.items()})
    dir_w = float(weights.get("dir") or 0.0)
    field_ws = tuple(float(weights.get(field) or 0.0) for field in LABEL_V2_REG_FIELDS)
    loss = torch.zeros((), device=labels.device, dtype=torch.float32)
    weight_sum = 0.0
    last_logits = outputs[0]
    smooth = float(label_smoothing)
    for j in range(n_h):
        logits = outputs[j]
        last_logits = logits
        target = labels[:, j]
        valid = target >= 0
        head_w = 1.0
        if horizon_weights is not None and j < len(horizon_weights):
            head_w = float(horizon_weights[j])
        if head_w <= 0.0:
            continue
        head_loss = torch.zeros((), device=labels.device, dtype=loss.dtype)
        parts = 0.0
        if dir_w > 0.0 and bool(valid.any()):
            head_loss = head_loss + dir_w * nn.functional.cross_entropy(
                logits[valid],
                target[valid],
                weight=class_weights,
                reduction="mean",
                label_smoothing=smooth,
            )
            parts += dir_w
        if path_labels is not None:
            pred = torch.cat(
                [_as_col(outputs[n_h + j * n_f + k]) for k in range(n_f)],
                dim=-1,
            )
            y_path = path_labels[:, j, :]
            for k, field_w in enumerate(field_ws):
                if field_w <= 0.0:
                    continue
                mask = torch.isfinite(y_path[:, k])
                if not bool(mask.any()):
                    continue
                head_loss = head_loss + field_w * nn.functional.smooth_l1_loss(
                    pred[mask, k],
                    y_path[mask, k],
                    reduction="mean",
                )
                parts += field_w
        if parts <= 0.0:
            continue
        loss = loss + head_w * (head_loss / float(parts))
        weight_sum += head_w
    if weight_sum <= 0.0:
        return last_logits.sum() * 0.0
    return loss / float(weight_sum)


def fusion_lr_scheduler(
    opt: torch.optim.Optimizer,
    lr_schedule: str,
    epochs: int,
) -> Optional[Any]:
    """Build cosine, plateau, or no LR schedule. Plateau patience is 4 epochs."""
    kind = str(lr_schedule).lower()
    if kind == "cosine":
        return torch.optim.lr_scheduler.CosineAnnealingLR(
            opt, T_max=max(int(epochs), 1)
        )
    if kind == "plateau":
        return torch.optim.lr_scheduler.ReduceLROnPlateau(
            opt, mode="min", factor=0.5, patience=4
        )
    return None


def step_fusion_scheduler(scheduler: Optional[Any], val_loss: float) -> None:
    """Step cosine (epoch) or plateau (val loss). No-op when schedule is off."""
    if scheduler is None:
        return
    if isinstance(scheduler, torch.optim.lr_scheduler.ReduceLROnPlateau):
        scheduler.step(val_loss)
        return
    scheduler.step()


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
    path_task_weights: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """AdamW + early stopping on validation CE. Never sees the test loader."""
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = fusion_lr_scheduler(opt, lr_schedule, epochs)
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
        windows, labels, path_labels = unpack_fusion_batch(batch)
        outs = model(*windows)
        return compute_fusion_loss(
            outs,
            labels,
            path_labels=path_labels,
            class_weights=cw,
            label_smoothing=float(label_smoothing),
            horizon_weights=hw,
            path_task_weights=path_task_weights,
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
        prev_lr = float(opt.param_groups[0]["lr"])
        step_fusion_scheduler(scheduler, val_loss)
        new_lr = float(opt.param_groups[0]["lr"])
        lr_note = f"  lr={new_lr:.2e}" if new_lr < prev_lr else ""
        print(
            f"epoch {epoch + 1:03d}  train={train_loss:.4f}  "
            f"val={val_loss:.4f}{lr_note}"
        )
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
        "last_lr": float(opt.param_groups[0]["lr"]),
    }
