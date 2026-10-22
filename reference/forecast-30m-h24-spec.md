# BTCUSD 30-minute forecast specification (Phase 1)

Research contract for a new offline forecasting line. Live v11 fusion is unchanged.
Do not copy an artifact into `agent/model_storage/`. Do not send orders.

Phase 1 freezes the data snapshot, the 12-hour horizon rule, and the holdout cut.
It does not define features, fit a model, or read the holdout for any score.

## Clock

| Item | Value |
| --- | --- |
| Instrument | BTCUSD |
| Timezone | UTC |
| Bar | 30 minutes, closed candle |
| Signal | Close of bar `t`. High and low of bar `t` are known and must not enter a target. |
| Horizon | Bars `t+1` through `t+24` |
| Wall clock | 12 hours, 43,200 seconds |
| Lookback | Independent of the horizon. Features may use bars at or before `t` only. |

A row is horizon-eligible only when every timestamp `t + k * 30 minutes` for
`k = 1..24` exists in the series. Missing bars are not filled. The last 24
bars of a file are ineligible because their horizon would extend past the file.

## Measured snapshot

Audited 2026-10-21 from `export/fusion_diagnostics/btcusd_30m_raw.parquet`.

| Check | Result |
| --- | --- |
| SHA-256 | `7b64fb0696d121d02d3ae209b1cfbaa85991ca0281135ae1d2a1bea16005145e` |
| Rows | 43,200 |
| First bar | 2024-04-10 14:00 UTC |
| Last bar | 2026-09-27 13:30 UTC |
| Duplicates | 0 |
| Off-grid timestamps | 0 |
| Irregular intervals | 0 |
| Completeness | 1.0 |
| Invalid OHLC rows | 0 |
| Horizon-eligible rows | 43,176 |
| Tail-ineligible rows | 24 |
| Gap-ineligible rows | 0 |
| Provisional source | Accepted |

The file ends on 2026-09-27, before this audit. It is a fixed snapshot, not a
live feed. Replacing it requires a new hash, a new audit, and a new split file.
The cache matches the repository's Delta Exchange India public-candle layout
(OHLCV plus `funding_rate` and `open_interest`). No separate download manifest
was stored beside the parquet. The hash above is the provenance for this phase.

`funding_rate` is null on 4 rows (non-null rate 0.999907). `open_interest` is
complete. Both columns stay out of the feature contract until a later phase
approves them. Phase 1 does not use them.

Authoritative copies: `export/forecast_30m/data_audit.json` and
`research/forecast_30m/configs/splits.yaml`.

## Split

The holdout is the last 15% of sorted rows. The fraction is a rule, not a date
chosen by inspecting prices. Purge width is 24 bars. The cut does not move.

| Block | Start (inclusive) | End | Rows |
| --- | --- | --- | --- |
| Development | 2024-04-10 14:00 UTC | 2026-05-15 14:00 UTC, exclusive | 36,720 |
| Holdout | 2026-05-15 14:00 UTC | 2026-09-27 13:30 UTC, inclusive | 6,480 |

Holdout status is `unread`. Tuning, feature drops, calibration, and threshold
selection stay inside development. A development signal whose 24-bar path
crosses 2026-05-15 14:00 UTC is unlabeled for supervised training. Those bars
may still be used as history for an earlier signal.

## Targets

Implement these in Phase 2. Do not train against the old opportunity label
`LONG / SHORT / NO_TRADE`, the sweep's same-bar stop-first rule, or Label V2's
5-minute clock.

Target A is multiclass direction from the close-to-close return over the 24
bars: `BEARISH`, `NEUTRAL`, `BULLISH`. The neutral band is `theta * ATR / close`.
Theta is chosen by the pre-registered rule below, on the development prefix only.

Target B is `forward_return_24 = close[t+24] / close[t] - 1`, with the log
return stored beside it. The baseline is a zero return.

Target C stores a four-way path code and two binary heads.

| Code | Meaning |
| --- | --- |
| `TP_FIRST` | Profit barrier prints on an earlier bar than the stop |
| `SL_FIRST` | Stop prints on an earlier bar than the profit barrier |
| `EXPIRY` | Neither barrier prints inside the 24 bars |
| `AMBIGUOUS` | Both barriers trade on the same future bar |

`long_tp_first_24` and `short_tp_first_24` are true only for `TP_FIRST`.
The research entry reference is `close[t]`. Distances use a causal 14-period
ATR known at `t`. Same-bar ambiguity stays `AMBIGUOUS` in the label. A later
profit-and-loss report may score that case as a stop. The classifier must not
be trained as if the stop were observed first.

Target B is the ending price. Target C is which barrier prints first. They are
not substitutes.

Targets D (future realized volatility), E (MFE/MAE), and F (regime at time `t`)
wait until A–C pass their gates.

## v1 rules

These rules were fixed before the first development measurement. The v1 holdout
was scored once under them. They are the record of that run, not the rule for
the next one.

Round-trip cost is `2 * (taker_fee_rate + slippage_bps / 10000)` using the
agent defaults `TAKER_FEE_RATE = 0.0005` and `SLIPPAGE_BPS = 5`. That is
0.002, or 20 basis points. It is the configured fee plus slippage, not a
spread measured from the parquet and not the old 0.16% research figure.
Stress costs are 1.5× and 2× that rate.

Theta grid: 0.25, 0.40, 0.50, 0.75, 1.00. A value passes only when each
direction class is at least 15% of development labels, the bullish mean return
is positive, the bearish mean return is negative, and the gap between those
means is at least the median band width. Prefer 0.50 when it passes. Otherwise
take the passing value with the largest return gap. If none pass, do not train
direction.

Barrier grid, as ATR multiples `(tp, sl)`: (1, 1), (1.5, 1), (2, 1),
(2, 1.5), (2, 2), (3, 1.5), (3, 2), (3, 3). A pair passes only when, on both
sides, each of TP-first, stop-first, and expiry is at least 10% of labels,
ambiguous / (TP-first + ambiguous) is at most 5%, and the median take-profit
distance is at least 4× the round-trip cost. Among passing pairs, take the
highest minimum path rate, then the higher cost ratio. Ambiguous rows are kept
in the path code and dropped from the binary heads. If none pass, do not train
the barrier heads.

Entry for these labels remains `close[t]`. A next-bar fill check is not part
of this run.

Walk-forward uses four expanding edges inside the development rows that remain
after a final 15% calibration block and a 24-bar purge are removed. Optuna is
capped at 8 trials per target, on the algorithm that won the default-parameter
comparison. The search never sees the calibration block or the holdout.

Primary fold score is the mean of the metric over the 24 non-overlapping
phases (`bar_index % 24 == offset`). Direction uses macro-F1, higher better.
Return uses MAE against a zero forecast, lower better. Barrier heads use Brier
score against the training base rate, lower better. Gate 4 requires a strict
win on at least two folds.

Gate 5 uses non-overlapping phases on the holdout only. It passes when the
median phase has more than 20 trades, positive expectancy at 1× and 1.5×
cost, profit factor above 1 at 1× cost, and a drawdown no worse than −15%
of cumulative trade returns. Thresholds are chosen on the development
calibration block only. If Gate 4 fails for every target, the holdout file
is not scored.

## Still deferred

- Targets D, E, and F.
- Funding and open interest as features.
- Wiring forecasts into the agent. Orders stay disabled.

## v1 measured label choice

Development rows used for the choice: 36,683. Dataset rows after feature warmup: 36,614 development and 6,454 holdout.

Theta **0.50** passed the preferred-value rule. Class shares were bearish 41.1%, neutral 15.1%, bullish 43.7%. The bullish-minus-bearish mean return gap was 0.0279, above the median band of 0.00211.

Barrier **3 ATR take-profit and 3 ATR stop**. Median take-profit distance was 6.32× the 0.002 round-trip cost. On the development path, long outcomes were 11,724 TP-first, 11,847 stop-first, 13,108 expiries, and 4 ambiguous. The short counts are the mirror. Ambiguous share was about 0.03%.

## v1 results

Walk-forward primary scores are the mean across the 24 non-overlapping phases. The holdout was scored once. Orders were not sent.

| Target | Development result | Holdout, scored once |
| --- | --- | --- |
| Return MAE | LightGBM 0.01136 vs zero-return 0.01131. Gate 4 failed, 0 of 3 folds. | Not scored. |
| Direction macro-F1 | LightGBM 0.331 vs majority 0.204. Gate 4 passed, 3 of 3 folds. | Model 0.255. Development majority class on the same rows: 0.203. |
| Long TP-first Brier | XGBoost 0.209 vs base rate 0.217. Gate 4 passed, 3 of 3 folds. | Model 0.206. Development base rate on the same rows: 0.220. |
| Short TP-first Brier | XGBoost 0.209 vs base rate 0.218. Gate 4 passed, 3 of 3 folds. | Model 0.216. Development base rate on the same rows: 0.221. |

The short model kept only `hour_sin`, `hour_cos`, and `dow_sin`. Its development gain is a clock effect, not a price effect. The long model kept eight columns, including returns, RSI, slope, and volume. Direction kept twelve columns.

Gate 5 failed. At the 0.45 / 0.45 thresholds chosen on the calibration block, the holdout median phase had 19 trades, expectancy −0.0023, and profit factor 0.36. At 1.5× cost the expectancy was −0.0074. The artifact is not approved for trading.

## v1 gates

| Gate | Status |
| --- | --- |
| 1. Data integrity | Passed. Zero duplicates, zero invalid OHLC, zero gaps. |
| 2. Label correctness | Passed the synthetic path tests, including same-bar ambiguity and a gap. |
| 3. Leakage-free evaluation | Passed. Chronological folds, a 24-bar purge, development-only tuning. Holdout scored once. |
| 4. Forecast value | Passed for direction and both barrier heads. Failed for the return forecast. |
| 5. Economic value | Failed. After-cost expectancy is negative and the trade count is below the pre-registered floor. |
| 6. Operational readiness | Artifact written. `orders_enabled` is false. It is not registered with the live agent. |

## v2 rules

These rules were written after the v1 holdout failed. That holdout is closed.
v2 refits on the original development prefix only. Confirmation needs bars
after 2026-09-27 and a new frozen tail. The cost stays 0.002.

Theta uses the same grid and the same 15% class floor. A value also has to put
the median neutral band at or above 1.5 round trips, and each directional
class mean has to clear the round trip itself. The smallest passing theta is
kept. That makes a directional label a move larger than the cost.

A barrier still needs each of TP-first, stop-first, and expiry on at least 10%
of labels, and an ambiguous share of at most 5%. It also needs unconditional
expectancy no worse than −5 basis points, and an empirical TP-first rate
within 5 points of the precision required to break even after cost. Symmetric
pairs are one path, so they are not trained as two heads. Among the pairs that
remain, the highest unconditional expectancy is kept. If none remain, the
barrier heads are not trained.

Direction's fold score is multiclass log loss against the training class prior.
A fold counts only when the model is at least 0.01 better. Return still uses
MAE against zero, and a fold counts only when MAE is at least 1% lower. A
barrier fold, if one is trained, must show positive expectancy at the
breakeven probability, with at least 20 trades. Two such folds are required.
Optuna stays off until a default tree passes that test. Ablation drops a
feature only when removing it worsens the score by a set minimum on two folds.
A head whose remaining columns are only the hour and weekday is rejected.

Thresholds on the calibration block must have positive expectancy and a profit
factor above 1, along with the existing trade count. Phases with no trades do
not enter the expectancy median. The v1 holdout file is not opened for a score.

## v2 development result

Development rows: 36,683. Theta **0.75** was the smallest band that covers 1.5
round trips. Class shares were bearish 37.6%, neutral 22.5%, bullish 40.0%.
The median band was 0.00316. Theta 0.50 failed because its band was 0.00211.

No barrier passed. Every pair lost about 0.20% per trade with no model, and
the empirical TP-first rate sat 19 to 26 points below breakeven. The closest
expectancy was −0.00196 at 3 ATR profit and 2 ATR stop. The closest precision
gap was −0.186 at 3 ATR profit and 1.5 ATR stop. Barrier heads were not trained.

Return MAE was LightGBM 0.01160 against a zero forecast of 0.01131. Gate 4
failed, 0 of 3 folds. Direction log loss was XGBoost 1.068 against the class
prior 1.071. One fold cleared the 0.01 lift and two did not, so Gate 4 failed.
Optuna did not run. The v1 holdout was not scored. The artifact contains no
model, and orders stay off.

## v3 rules

These rules were written before any bar after 2026-09-27 was read. The v1
holdout stays closed. The v2 artifact stays empty. v3 is a separate pipeline
and a separate export directory. Nothing is copied into `agent/model_storage/`.
Orders stay off.

One configuration is registered. There is no threshold grid, no Optuna, no
LightGBM comparison, and no LSTM or Transformer.

The signal is the close of bar `t`. The fill is the open of bar `t+1`. Path
high and low run from `t+1` through `t+24`. The horizon end is the close of
`t+24`. A gap through one barrier at the fill open is that barrier. Missing
bars are not filled.

Events only: a symmetric CUSUM on close-to-close log returns with threshold
0.02. The threshold is fixed. One barrier is taken from the fill price:
take-profit 2% and stop 1%, vertical limit 24 bars. Round-trip cost stays
0.002. Breakeven precision is 0.40.

The v2 economic screens still apply on development events: each path rate at
least 10%, ambiguous share at most 5%, unconditional expectancy no worse than
−5 basis points, and the empirical take-profit rate within 5 points of
breakeven. A failure stops the run before a model is fit.

One XGBoost policy uses the existing default tree. Two probabilities, one
position: take the side whose probability is at least 0.40 and is the larger
of the two. Otherwise flat. A new event while a 24-bar position is open is
skipped. Walk-forward stays inside development. The policy must show positive
traded expectancy, a profit factor above 1, and at least 20 trades. The return
head is not a promotion path.

Development labels end before 2026-05-15 14:00 UTC. The spent holdout,
2026-05-15 14:00 through 2026-09-27 13:30, is embargoed: those labels are
neither fit nor scored. Prices in that window may be used only as causal
history. Confirmation is bars strictly after 2026-09-27 13:30. It is scored
only after the development gate passes, and only once.

The original parquet and `splits.yaml` are not overwritten. New candles are
appended from the public Delta history endpoint into
`export/forecast_30m/v3/btcusd_30m_extended.parquet`.

On the confirmation tail, the one-position policy is compared with buy-and-hold
(first confirmation open to last close, one round trip). Circular block
bootstrap uses block length 48 bars, 1,000 draws, and seed 42. A pass requires
at least 20 trades, expectancy above 0, profit factor above 1, drawdown no
worse than −15%, and a bootstrap mean above both zero and buy-and-hold at 5%.
Fewer than 20 trades is `insufficient_confirmation_window`. A development
failure writes that reason and does not read confirmation labels.

## v3 development result

The extended snapshot has 44,392 rows, 2024-04-10 14:00 UTC through
2026-10-22 09:30 UTC. Completeness 1.0. The original hash is unchanged. The
spent holdout stays `scored_once` in `splits.yaml`.

CUSUM 0.02 produced 1,235 development events, 154 embargo events, and 23
confirmation events. The 2% / 1% barrier cleared the path-rate and ambiguous
screens. Unconditional expectancy was −0.00201. The long take-profit rate was
0.223 against breakeven 0.40, a gap of −0.177. The screen failed
`no_skill_expectancy_too_negative` and `tp_rate_far_below_breakeven`. No model
was fit. Confirmation labels were not read. The artifact contains no model,
and orders stay off.

## v3 ranking rules

These rules were written after the v3 barrier screen failed and after the
economic calculation was audited. They do not change the CUSUM threshold, the
2% / 1% barrier, or the 20-basis-point cost. They do not open the embargo or
the confirmation tail. A ranking result is not a promotion.

The question is whether an XGBoost model can rank the existing development
events by outcome quality. The data are
`export/forecast_30m/v3/dataset_development.parquet` only.

Walk-forward stays inside development. Each fold fits a constant take-profit
base rate and the default XGBoost tree on that fold's training events. LightGBM
and Optuna stay off. Out-of-fold rows are concatenated for the economic and
quintile scores.

Statistical ranking: for each side, Brier score of the XGBoost probability
against the fold's training base rate. A head ranks if Brier is lower on at
least two folds.

Quintile diagnostic: five bins of out-of-fold predicted take-profit
probability. Each bin reports mean net path return of taking that side. This
is a ranking picture, not a selection rule.

Economic subset: on the out-of-fold probabilities, take the side whose
probability is at least 0.40 and is the larger of the two. Skip a new event
while a 24-bar position is open. That subset must show at least 20 trades,
expectancy above 0, and profit factor above 1. Compare it with taking every
out-of-fold event (the always-in mean). The uninformed base-rate policy is
also scored; with a 0.22 base rate it is expected to stay flat at the 0.40
cutoff.

None of these tests reads confirmation labels. A ranking pass does not score
the tail after 2026-09-27.

## v3 ranking result

Development parquet only: 1,235 events. Walk-forward scored 786 out-of-fold
rows. Confirmation labels were not read.

The long head beat the training base-rate Brier on 2 of 3 folds. The lifts
were 0.00055 and 0.00004. The short head lost all 3 folds. Quintiles of
predicted take-profit probability are not monotonic. The top long bin had
mean probability 0.38 and mean net return −0.0031, worse than the middle
bins.

The uninformed policy placed 0 trades: fold base rates were 0.24 to 0.27,
below the 0.40 cutoff. XGBoost placed 63 trades. Out-of-fold expectancy was
−0.00073, profit factor 0.89. Always-in on the same rows was −0.00208. The
selected subset lost less than taking every event and still lost money.

Economic ranking failed. Orders stay off. The confirmation tail was not
opened.

## v4 rules

These rules were written after v3 showed that barrier-and-cost labels are a
different question from directional skill. v4 does not reuse v2 theta 0.75.
It does not train take-profit or stop-loss heads. Cost is not in the label
rule, the loss, or Gate 4. Confirmation after 2026-09-27 is not scored.
Nothing is copied into `agent/model_storage/`.

Every 30-minute bar is a candidate. The signal is the close of bar `t`. The
12-hour return that defines the class is marked from the open of `t+1` to the
close of `t+24`. Direction is BEARISH / NEUTRAL / BULLISH from that return
versus `theta * ATR / fill`. Theta is the smallest grid value whose three
class rates are each at least 15%. Cost screens are not applied.

Features are the v1 causal set plus a frozen pattern block: doji, hammer,
shooting star, bullish engulfing, bearish engulfing, inside bar, close broke
the prior 24-bar high or low, and a clipped consecutive-close run. All of
those use bars at or before `t`. Clock-only models are still rejected.

Training is one XGBoost direction head against the class-prior baseline.
Default trees. Optuna off. LightGBM is not compared. Gate 4 is multiclass
log loss with a 0.01 lift on at least two walk-forward folds. Argmax maps
BEARISH to sell, BULLISH to buy, and NEUTRAL to hold. That map is reporting
only.

The original snapshot is the source, so bars after 2026-09-27 never enter
the file. Development labels end before 2026-05-15 14:00. Outputs go to
`export/forecast_30m/v4/`. Orders stay off.

## v4 development result

Theta **0.50** was the smallest class-floor value. Neutral was 15.1%. Theta
0.25 and 0.40 failed `neutral_below_floor`. Development rows after warmup:
36,614. Entry was the next-bar open.

XGBoost mean log loss was 1.016 against the class prior 1.014. Fold scores
were worse than the prior on two folds and better on one (lift 0.018). Gate 4
failed, 1 of 3. Optuna did not run. The artifact contains no model. Orders
stay off. Confirmation was not scored.

## Reproduce


```bash
python -m research.forecast_30m --source export/fusion_diagnostics/btcusd_30m_raw.parquet
python -m research.forecast_30m.pipeline
python -m research.forecast_30m.pipeline_v3
python -m research.forecast_30m.pipeline_v3_ranking
python -m research.forecast_30m.pipeline_v4
pytest tests/unit/test_forecast_30m_integrity.py tests/unit/test_forecast_30m_labels.py tests/unit/test_forecast_30m_evaluation.py tests/unit/test_forecast_30m_v3.py tests/unit/test_forecast_30m_v4.py -q
```

The audit exits with code 2 when the snapshot fails the provisional-source rule
(fewer than 20,000 unique rows, a duplicate timestamp, invalid OHLC, an
off-grid timestamp, or an irregular interval).
