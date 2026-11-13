# 15-minute recognition spec

Research-only contract for BTCUSD pattern recognition. This track does not place orders, does not emit buy or sell signals, and does not replace the live `forecast_30m` path.

Specification version: `recognition-15m-v2`.

## Window

Each example is 48 completed 15-minute bars (12 hours), ending at a closed bar. Bars are resampled from `export/fusion_diagnostics/btcusd_5m_raw.parquet`. Duplicate 5-minute timestamps keep the last row. A 15-minute bar is emitted only when the bucket contains the three clock-aligned 5-minute bars. Incomplete buckets are dropped and are not filled.

Warmup before the window may compute the 14-bar average true range and the 48-bar volume baseline. Warmup bars are not pattern spans and are not extra rows in the tensor.

## What the model is allowed to see

Two input modes are trained. Both are scaled with statistics fit on the training windows only.

Raw channels, each price measured from the first close in the window and divided by the ATR at the window end, with volume divided by the volume baseline at the window end:

- `open_atr`
- `high_atr`
- `low_atr`
- `close_atr`
- `volume_ratio`

Engineered channels, each already in ATR units or a ratio of the same bar:

- `body_size_atr`
- `upper_wick_atr`
- `lower_wick_atr`
- `range_atr`
- `body_to_range`
- `upper_wick_to_range`
- `lower_wick_to_range`
- `close_location`
- `body_sign` (sign of close minus open)
- `close_change_atr`
- `volume_ratio`
- `level_support_dist_atr`
- `level_resistance_dist_atr`
- `level_at_support`
- `level_at_resistance`
- `level_support_touches`
- `level_resistance_touches`
- `level_range_position`

`body_sign` is the sign of the candle body. It is not a bullish or bearish pattern class.

The seven `level_*` channels are support and resistance. A swing high or swing low enters the calculation only at the bar where price has reversed by 1.5 ATR, the same confirmation used for market-state labels. The level is the nearest confirmed extreme inside the last 60 bars on that side of price. When those 60 bars contain no extreme on one side, the last confirmed extreme on that side is kept. Distance is in ATR. `level_at_support` and `level_at_resistance` are 1 when price is within 1 ATR of that level. Touch counts are how many confirmed extremes in the 60-bar window sit within 0.5 ATR of the chosen level. `level_range_position` is 0 at support and 1 at resistance. Rows stay empty until both a swing high and a swing low have been confirmed.

## What the model must not see

The feature tensor rejects any of the following:

- Prefixes `cdl_`, `chp_`, `sr_`, `tl_`, `bo_` from the candle and chart rule engines.
- `PATTERN_COLUMNS` from the 30-minute forecast contract, including `hammer`, `bullish_engulfing`, `inside_bar`, and `close_broke_high_24`.
- `NATIVE_STRUCTURE_COLS` from the transformer structure contract, including `hh_count`, `failed_break`, and `dist_neck_atr`.
- Forecast labels and trade outcomes: `y_direction`, `forward_return_24`, `forward_log_return_24`, `long_tp_first_24`, `short_tp_first_24`, `tp_pct`, `sl_pct`, `buy`, `sell`, `hold`, `expectancy`.
- Rule-card fields: `conventional_name`, `directional_bias`, `context`, `abstain`.
- Head A class names, market-state names, and structure-tag names.

Swing detection for labels uses a causal ATR zigzag (reversal of 1.5 ATR). `argrelextrema` is not used, because it confirms a swing with bars to the right of the candidate.

A label or feature at bar `t` is a function of bars at or before `t`. Training, validation, and test are chronological. The last bar of a training window and the last bar of the next validation window are at least 48 bars apart, so the two windows do not share bars. The same gap is required between validation and test. Reported metrics use windows at least 48 bars apart.

## Head A — geometric families

Head A is a per-bar multi-label detector. The class is the shape, not the textbook name that already contains a direction.

| Class | Rule at the completion bar |
| --- | --- |
| `long_lower_wick` | Lower wick at least twice the body, opposite wick under 20% of the range, body over 5% of the range, range over half an ATR |
| `long_upper_wick` | Mirror of `long_lower_wick` |
| `doji` | Body under 10% of the range and range over half an ATR |
| `marubozu` | Body at least 85% of the range and each wick under 8% |
| `engulfing` | Current body contains the prior body, opposite body signs, both bodies over 0.25 ATR |
| `harami` | Current body sits inside a prior body over 0.40 ATR, opposite signs |
| `piercing_dark_cloud` | Opposite second candle closes through the prior midpoint without fully passing the prior open |
| `tweezer` | Adjacent highs or lows within 0.15 ATR, opposite signs, both bodies over 0.20 ATR |
| `star` | Large body, small body, large opposite body whose close passes the first candle's midpoint |
| `soldiers_crows` | Three same-sign bodies over half the range, closes stepping with the trend, opposite wick under 25% |

Thresholds live in `research/recognition_15m/contract.py`. Loss is binary cross-entropy with a positive-class weight computed inside the training split and clipped at 20.

## Rule card — names and bias, not a trained head

Conventional names and directional bias are stored on a separate record and dropped before the tensor is built. They are not a neural head in this version. `abstain` marks insufficient context. It is not a softmax class.

| Geometry and context | Conventional name | Bias | Abstain |
| --- | --- | --- | --- |
| Long lower wick after a decline | `hammer` | bullish | no |
| Long lower wick after an advance | `hanging_man` | bearish | no |
| Long lower wick after a flat prior | `long_lower_wick` | context_dependent | yes |
| Long upper wick after an advance | `shooting_star` | bearish | no |
| Long upper wick after a decline or a flat prior | `inverted_hammer` or `long_upper_wick` | context_dependent | yes |
| Doji | `doji` | neutral | no |
| Marubozu | `marubozu` | sign of the body | only if the body is flat |
| Engulfing, harami, piercing or dark cloud, tweezer, star, soldiers or crows | name follows the completing candle's sign | that sign, or `context_dependent` when the tweezer has both sides | when the sign is flat or both tweezer sides fire |

Prior context is the close one bar back compared with the mean of the five closes ending at that prior bar. A relative gap under 0.1% is `after_flat`. The comparison does not use the current candle and does not use any later candle.

## Head E — market state

One state for the window, using zigzag swings whose extreme and confirmation bar both lie inside the 48 bars:

- `uptrend`: at least two higher-high or higher-low events and they outnumber the bearish events
- `downtrend`: the mirror
- `transition`: the last event opposes a majority of at least two events on the other side
- `range_bound`: at least two events and neither side qualifies as a trend
- `indeterminate`: fewer than two qualifying events

Structure tags on the same head, still labels rather than inputs: `hh_hl`, `lh_ll`, `mixed`, `none`. Loss is categorical cross-entropy with class weights from the training split. Task weights are not used to hide a rare class.

## Heads that are specified and not trained

Chart-pattern identity, chart-pattern bias, formation status, observed breakouts, and zone geometry need a written confirmation rule per pattern before a loss is attached. A formation that depends on bars outside the 48-bar window is `partially_observable`. Those coordinates stay masked. No head is trained on future returns, future prices, stop or target hits, expectancy, or an entry decision.

## Trainers

- Shared causal TCN. Head A reads every timestep. Head E reads the last timestep. The short local fit uses clipped SGD when this machine cannot construct AdamW. The Colab fit uses AdamW.
- The same heads are trained on the raw channels and on the engineered channels in the local smoke run. The Colab run trains the engineered channels.
- XGBoost is a baseline for window-level presence of each geometric family. It does not emit spans, repeated instances, or geometry.
- Batches may be shuffled inside the training split. Validation selects the epoch. Test metrics are computed once, on windows at least 48 bars apart.

## Colab training

`python -m research.recognition_15m` stays the short local fit. The intense run is the generated notebook `scripts/colab/recognition_15m_colab.ipynb`, rebuilt with `python scripts/colab/build_recognition_15m_notebook.py`. Upload that notebook to Colab and run it from top to bottom. The training code is inside the notebook, so Colab does not clone this repository. The notebook fetches BTCUSD 5-minute candles from the public Delta Exchange history API and writes `/content/btcusd_5m_raw.parquet`. The notebook does not mount Google Drive. The notebook installs PyTorch, Optuna, SHAP, XGBoost, and Matplotlib, then calls `run_colab`. The checkpoint, report, and PNG figures are written to `/content/export/recognition_15m/colab/`, and the zip contains that set. The cell after the fit draws the same figures.

Search stays inside the outer train and validation span. Three chronological folds each keep the 48-bar purge. Optuna TPE runs 30 trials with a median pruner. A trial may choose hidden width 32, 64, or 128, dilation depth, learning rate, batch size, and the positive-class weight clip. Each trial trains at most 20 epochs and stops early on validation loss. The trial score is the mean of Head A macro-F1 and Head E macro-F1 on validation windows 48 bars apart. After the study, one TCN is refit on the development train split for at most 40 epochs, again stopping early on validation loss, and the sealed test is scored once. The study may use stride 4. The final fit uses stride 1 when the GPU holds every training window. Published test metrics stay on windows 48 bars apart.

Before that fit, three future-bar perturbations check a sample of the series. On the training windows, Spearman correlation is computed between each engineered channel (the last bar, and the window mean) and each geometric family plus the market-state code. The report stores that matrix and flags pairs whose absolute correlation is at least 0.5. The correlation figure draws both reductions as heatmaps and boxes each flagged pair. A high correlation between `body_to_range` and `doji` is the rule definition showing through. TreeSHAP explains the XGBoost presence baseline on a fixed sample of those same windows and sums each channel across the 48 bars. The SHAP figure ranks those channel totals. Neither audit adds a column, and neither can introduce a candle-rule flag, a chart-rule flag, or a forecast label.

The sealed-test section of `export/recognition_15m/colab/report.json` records per-class precision, recall, support, and macro-F1 for Head A and Head E, plus the expected calibration error of Head A probabilities and a reliability table. That calibration describes recognition reliability. The report also records the train and validation loss of the refit, the validation scores beside the sealed test, the correlation matrix, the SHAP channel ranking, the purge gaps, and every trial. It does not record a buy, a sell, expectancy, Sharpe, or a promotion flag. The same checkpoint is installed at `agent/model_storage/JackSparrow_Recognition_BTCUSD_15m/tcn_colab.pt`. The agent attaches its market state and geometry to the forecast decision. The forecast bundle remains the order source.

## How to run

```bash
python -m research.recognition_15m
```

Metrics are written to `export/recognition_15m/metrics.json`. The Colab checkpoint installed under `agent/model_storage/JackSparrow_Recognition_BTCUSD_15m/` is loaded by model discovery. It is not a `ForecastModelNode`.
