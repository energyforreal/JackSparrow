# v43 State Head — Phase 5 Roadmap (staged)

Items below are intentionally **not** required for the first state-head training run.

## Horizon-specialised feature masks

After Run 11 importance output, populate `V43_HORIZON_FEATURE_MASKS` in
`feature_store/jacksparrow_v43_labels.py` and pass `tier_masks` into
`train_state_heads_from_feature_matrix` / per-horizon regressors.

## Walk-forward validation

Use `walk_forward_fold_indices()` in `feature_store/jacksparrow_v43_train_multihead.py`
for 3-fold expanding-window evaluation of state-head balanced accuracy / AUC.

## Shared neural encoder (PyTorch)

Consider only if tree-based state heads plateau below 60% balanced accuracy on regime.
Architecture: shared dense encoder → task-specific softmax/sigmoid heads.

## Live microstructure

Collect `bid_ask_imbalance` and `spread_bps` via `V43_TICKER_SNAPSHOTS_CSV` before
re-enabling scalp-tier features in masks.
