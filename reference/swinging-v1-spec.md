# Swinging v1

Hybrid algorithmic and machine-learning research for BTCUSD perpetual futures.
This track does not place orders. Live risk, position sizing, and execution stay
on the existing trading handler.

## Storage

Historical candles, features, setups, outcomes, Optuna files, and experiment
artifacts are written only on the local disk. On Google Colab that root is
`/content/JackSparrow/data`. The notebooks reconstruct those files from the
public Delta history API after a runtime reset. They do not mount Google Drive
or call a Drive API.

Do not commit parquet datasets, intermediate training frames, or checkpoints.
`*.parquet` is gitignored. Approved model bundles are copied by hand into
`agent/model_storage/` only after a separate promotion review, and the loader
still refuses `orders_enabled: true`.

## Data

Public endpoint: `GET https://api.india.delta.exchange/v2/history/candles`.
No API key. Symbol `BTCUSD` at `5m`, `15m`, `1h`, and `4h`, plus `MARK:`,
`FUNDING:`, and `OI:` when the API returns them. Pagination uses
`scripts/colab/transformer_data.py` `fetch_candles` (2,000-bar windows, retries,
backward walk from the oldest returned timestamp). The manifest records the
earliest and latest timestamps actually stored.

## Features and setups

`research/swinging/features.py` is the only feature definition used for a
setup snapshot and for later inference. It calls `UnifiedFeatureEngine`,
`CandlestickPatternEngine`, `ChartPatternEngine`,
`add_market_structure_features`, and CPR `detect_swings`. A snapshot is built
on the prefix ending at the signal bar. Outcome and label columns are not
features.

Engine A (`research/swinging/setups.py`) emits breakouts, breakdowns, retests,
support bounces, resistance rejections, reversals, trend continuation,
candlestick rows, and chart-pattern rows. Rejected and neutral rows are kept.
Chart geometry reuses `research/cpr_mtf/candidates.py`. CPR breakout status is
a future annotation and is not copied onto the feature snapshot.

## Outcomes and models

`research/swinging/outcomes.py` enters at the next bar open, never at the
signal close. Five-minute bars resolve stop and target order inside a higher
timeframe bar. A bar that touches both, with no finer bar, exits at the stop.
Fees are 5 bps per side and slippage is 5 bps per side, matching the forecast
v5 round trip of 0.002 before funding. Funding is applied when a funding
series exists. Unresolved tails are dropped. Overlapping signals are not given
a second position.

Models are XGBoost and LightGBM classifiers and regressors. Optuna tunes on
the chronological development span only. Walk-forward comparison uses one
cost model and one fill for algorithm-only, ML-only, and hybrid decisions.
Recognition TCN accuracy is a separate research track and is not a trading
result.

## Runtime

Exported bundles carry `promotion_status=research` and `orders_enabled=false`.
`SetupEffectivenessNode` and `SREffectivenessNode` refuse any other manifest.
They do not contribute to order consensus and they do not call execution.

## Forecast promotion

`agent/model_storage/JackSparrow_Forecast_BTCUSD_30m/manifest.json` has
`development_gate_passed: false` and `promotion_override:
force_promote_live_floor_0.55` while `orders_enabled` is true.
`ForecastModelNode` now refuses that combination unless
`FORECAST_ALLOW_PROMOTION_OVERRIDE` is set. The research promoter does not
write `promotion_override`. The manifest file on disk is left unchanged.
