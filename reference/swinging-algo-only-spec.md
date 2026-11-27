# Swinging algo-only

Sub-branch of `swinging` for running the BTCUSD operation from a weighted
algorithmic score. Git cannot store a branch named `swinging/algo-only` while
the branch `swinging` exists, so this line is `swinging-algo-only`.

The parent branch and the model stacks stay in the tree. `mtf_fusion`,
`forecast_30m`, and `transformer_agent_synthesis` are unchanged when
`TRANSFORMER_DECISION_PATH` is not `algorithmic`.

## Decision

`TRANSFORMER_DECISION_PATH=algorithmic` scores closed 4h, 1h, 15m, and 5m bars
and emits the same `DecisionReadyEvent` as the model paths. It does not load
ONNX or joblib bundles. An empty model registry is not an error on this path.

Design weights, summing to 100:

| Component | Points |
| --- | --- |
| 4h EMA 20/50/200 trend and slope | 20 |
| 1h structure, BOS confirming, CHoCH invalidating | 20 |
| 15m chart pattern | 15 |
| Support or resistance rejection | 15 |
| 5m candle confirmation, including pin bars | 15 |
| Volume expansion | 10 |
| RSI and MACD momentum | 5 |

65–79 is a qualified setup. 80–100 is high quality. Below 65 is a hold.
These cutoffs are design values. They are not a proven edge.

Stops and targets use the existing 1.5 ATR stop and 2.5 ATR target. They travel
on the shared decision as proposed brackets. Confidence is the score divided
by 100. Position size stays zero on that object. The trading handler sizes the
entry from `entry_portfolio_margin_fraction`, capped by `max_position_size`.
A higher score does not increase the size.

The shared object carries a decision id, candle timestamp, score breakdown,
market context for 5m, 15m, 1h, and 4h, reasons, invalidation, and
`execution_authorized: false`. Model predictions are wrapped in the same
object without changing their signal, confidence, or size.

A live score holds when a required timeframe is missing, a candle is invalid,
the latest 5m bar is still open, or a closed bar is stale. Historical
walk-forward checks missing and invalid bars only.

## Orders

`ALGORITHMIC_ORDERS_ENABLED` defaults to false. The scorer cannot authorize an
order. Execution accepts `algo_signal_validated` only when the flag is true,
risk approval is present, the side is buy or sell, and the stop and target sit
on the correct side of price. A repeated decision id is still rejected.
The flag does not turn itself on after a backtest. ML orders still require
`ml_signal_validated`.

## Research loop

`research/swinging/mtf_score.py` is the only score definition.
`research/swinging/algo_walkforward.py` replays it through the existing
next-bar simulator, fees, slippage, funding, and purged walk-forward splits.
Optuna, when used, searches weights and the two cutoffs on the development
span. It does not fit XGBoost or LightGBM.

`research/swinging/models.py`, the Colab notebooks, and the setup and
support/resistance research nodes stay research sidecars.
