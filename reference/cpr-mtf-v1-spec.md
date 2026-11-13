# CPR-MTF v1 data contract

Research-only contract for multi-timeframe BTCUSD chart-candidate construction. This track does not place orders, does not emit buy or sell signals, and does not load a checkpoint from `agent/model_storage`.

Specification version: `cpr_mtf_v1`.

This milestone freezes the data, swing, candidate, annotation, and leakage contract. It does not train a TCN, run Optuna, or score a sealed test. Neural training stays blocked until preview charts have been reviewed and the annotation file contains reviewed rows.

## Instrument and bars

Each example is aligned to one prediction clock. The source is `export/fusion_diagnostics/btcusd_5m_raw.parquet`. Duplicate 5-minute timestamps keep the last row. Naive timestamps are read as UTC.

| Timeframe | Bucket | Source bars required |
| --- | --- | --- |
| `15m` | 15 minutes | 3 clock-aligned 5-minute bars |
| `1h` | 1 hour | 12 clock-aligned 5-minute bars |
| `4h` | 4 hours, floored on the UTC epoch | 48 clock-aligned 5-minute bars |

A bucket is emitted only when it contains exactly those source timestamps. Incomplete buckets are dropped and are not filled. Aggregation is open of the first source bar, high of the max, low of the min, close of the last source bar, and the sum of volume. A later bucket never revises an earlier one. Vendor 1-hour or 4-hour candles are not used.

The prediction clock is the end of a completed 15-minute bar. A higher-timeframe bar is included only when its own bucket end is at or before that clock. At 10:15 UTC the last 15-minute bar is 10:00–10:15, the last 1-hour bar is 09:00–10:00, and the 4-hour bar that closes at 12:00 is excluded. The 4-hour bar that closed at 08:00 remains the latest completed 4-hour bar.

## Sequence tensor

Each timeframe stores one causal series. The model window is the last 192 completed bars of that series, shape `(192, 20)`. The 48-bar and 96-bar windows are suffixes of those 192 rows. They are not recomputed on a truncated history. ATR period is 14. Volume baseline is the trailing 48 bars of that timeframe, including the current bar.

Emitted windows start at the first bar where both ATR and the volume baseline are finite, which is bar index 47. ATR itself is finite at index 13. Waiting for the volume baseline keeps the stored tensor finite. A 4-hour sample therefore needs more than 32 days of history.

Channels, in order:

| Channel | Definition at bar `t` |
| --- | --- |
| `open_atr`, `high_atr`, `low_atr`, `close_atr` | Price minus the previous close, divided by ATR. Bar 0 uses its own close as the previous close. |
| `body_size_atr` | Absolute body divided by ATR. |
| `upper_wick_atr`, `lower_wick_atr` | Wick length divided by ATR. |
| `range_atr` | High minus low, divided by ATR. |
| `body_to_range` | Body divided by the high-low range, or 0 when the range is flat. |
| `close_location` | Close location inside the high-low range, or 0 when the range is flat. |
| `volume_ratio` | Volume divided by the trailing volume baseline. |
| `swing_high_flag`, `swing_low_flag` | 1 on the bar that confirms that side, else 0. |
| `swing_high_prominence_atr`, `swing_low_prominence_atr` | Prominence on the confirmation bar, else 0. |
| `bars_since_confirmed_swing` | `log1p(bars since the last confirmation) / log1p(192)`. The value is 1 before any swing has confirmed, and 0 on the confirmation bar. |
| `swing_high_slope`, `swing_low_slope` | ATR per bar between the pivot bars of the last two confirmed swings on that side. 0 until two swings exist. |
| `swing_range_atr` | Absolute distance between the latest confirmed high price and the latest confirmed low price, divided by ATR. 0 until both sides exist. |
| `price_position_in_swing_range` | Close location between those two prices. 0.5 until both sides exist. |

The sequence allow-list rejects any other name. In particular it rejects `cdl_`, `chp_`, `sr_`, `tl_`, and `bo_` columns, forecast and trade-outcome names, `candidate_type_proposal`, and `candidate_quality_rule_score`. Support and resistance level channels from the 15-minute recogniser are not part of this tensor. `feature_store/pattern_features/chart_patterns.py` is not an input and is not a label source. Swing detection does not use `argrelextrema`.

## Swings

A swing is confirmed when price reverses by 1.5 ATR from the running extreme. ATR in that test is the causal ATR at the confirmation bar. The pivot bar and the confirmation bar are stored separately. A swing is visible at bar `t` only when its confirmation index is at or before `t`. The first high and the first low are kept. Prominence is the confirming reversal distance divided by ATR at the confirmation bar, so it is at least 1.5. `atr_at_pivot` is the causal ATR at the pivot bar, with a one-percent-of-price fallback when that ATR is not yet finite.

## Pattern classes

Identity is one of these 15 shape classes, in this order:

`double`, `triple`, `head_and_shoulders`, `flag`, `pennant`, `ascending_triangle`, `descending_triangle`, `symmetrical_triangle`, `rising_wedge`, `falling_wedge`, `ascending_channel`, `descending_channel`, `rectangle`, `broadening`, `cup_and_handle`.

Direction is `bullish`, `bearish`, or `neutral`. It is not a sixteenth identity class. A double top and a double bottom share `double`. Head and shoulders and inverse head and shoulders share `head_and_shoulders`. Proposal direction follows the structural slope or the impulse. For a wedge, that direction is the slope direction. It is not a textbook breakout opinion. Annotation direction is a separate field and may disagree with the proposal.

## Candidates

Generators run on each timeframe using swings whose confirmation is at or before the as-of bar and whose pivot lies inside the 192-bar window. Numeric tolerances in `research/cpr_mtf/contract.py` are proposal parameters, not ground truth.

- `double` and `triple` use consecutive same-side extremes within the similarity tolerance, with opposite swings between them.
- `head_and_shoulders` uses a five-swing sequence whose middle extreme exceeds both shoulders.
- `flag` uses an impulse of at least 3 ATR followed by a shorter countertrend consolidation with two boundary points on each side.
- `pennant` uses that same impulse test plus converging boundaries.
- Triangles, wedges, channels, `rectangle`, and `broadening` come from one slope classification of the latest confirmed highs and lows.
- `cup_and_handle` requires a left lip, a rounded low, a right lip, and a smaller handle. Those rows are marked `rounded_proxy`.

Deduplication keeps one row per timeframe, class, and first and last constituent confirmation time, preferring the higher rule score. Each timeframe keeps at most two proposals per family and at most 12 proposals. The sample pads to 36 candidates in timeframe order `15m`, `1h`, `4h`, with a validity mask.

The geometry vector has 22 channels. It includes timeframe id, width, height, boundary slopes and distances, convergence, divergence, swing counts, touches, fit error, price position, volume contraction and expansion, bars since the last boundary interaction, impulse, retracement, and a maturity ratio. The maturity ratio is how far the as-of bar sits through the proposed pivot span. It is not the annotation maturity class.

`candidate_type_proposal`, `candidate_quality_rule_score`, proposed direction, and constituent swing ids live in the proposal table. Boundary prices in that table use the close at the as-of bar as the price origin. Nothing copies the proposal class into an identity label.

Cross-timeframe pairs are emitted only for candidates on different timeframes. Pairs whose price ranges overlap and whose active intervals overlap are listed first. Other pairs fill the remaining slots. The list is capped at 32. The relationship field is left blank for a reviewer.

## Annotations and future breakouts

Annotations are JSONL, separate from the feature tensor. A blank row has an empty identity. Allowed identity values are the 15 classes, `reject`, or empty. Direction and maturity stay empty until a reviewer sets them. Maturity values are `developing`, `mature`, `confirmed`, and `invalidated`.

Future breakout targets are another table, at horizons of 12 and 24 bars of the candidate's native timeframe. The preliminary buffers are 0.20 ATR for a breach and 0.40 ATR for a single-close confirmation. Two consecutive closes beyond the 0.20 ATR buffer also confirm. These buffers are labelling parameters, not feature inputs.

| Status | Meaning |
| --- | --- |
| `no_breakout` | The horizon completes with no confirmed breach. |
| `upside_breakout` | Confirmed close through the upper boundary, or the proposal is bullish and that side breaks. |
| `downside_breakout` | Confirmed close through the lower boundary, or the proposal is bearish and that side breaks. |
| `invalidated` | A bullish proposal confirms through the lower boundary, or a bearish proposal confirms through the upper boundary. |
| `ambiguous` | One bar trades through both buffers, or the close satisfies both sides. |
| `masked` | The horizon extends past the last bar. |

A bullish proposal maps an upside confirmation to `upside_breakout` and a downside confirmation to `invalidated`. A bearish proposal does the mirror. A neutral proposal keeps the side names. These columns are forbidden in the sequence tensor.

## Splits

Development, outer validation, and sealed test are 70 percent, 15 percent, and 15 percent of 15-minute as-of indices, in time order. The purge between partitions is 384 fifteen-minute bars. That is the 24-bar, 4-hour breakout horizon measured in 15-minute bars, because one 4-hour bar contains 16 fifteen-minute bars. Historical input context may cross a boundary. Future labels may not.

## Preview

`python -m research.cpr_mtf` reads the 5-minute parquet when it is present, writes candlestick PNGs under `export/cpr_mtf/preview/`, and writes `export/cpr_mtf/audit.json`. Charts draw only swings whose confirmation bar is at or before the as-of index. The command does not download data. A missing parquet exits with status 1.

## What this milestone does not do

The package does not train a model, search hyperparameters, install a checkpoint, or change `research/recognition_15m`. Training-time arrays and preview charts call the same feature, swing, and candidate functions.
