# Label V2 specification (research)

Research path targets for JackSparrow. **Live v11 fusion is unchanged:**
2-class BEAR/BULL heads, NEUTRAL as `ignore_index`, no MFE/MAE, ATR SL/TP in
[`agent/core/fusion_policy.py`](../agent/core/fusion_policy.py).

The Colab research trainer now **trains** on 3-class direction plus
ret / long-short MFE/MAE (`FEATURE_CONTRACT_VERSION_V15`, four heads:
h10m/h15m/h30m/h1h). Persistence and TP/SL stay diagnostics. Do **not** copy a
research ONNX into `agent/model_storage/`. Live v11 is unchanged.

Frozen theta (from the four-horizon mix report, 259,188 labeled 5m bars):
all four heads `0.50`. No class is below the 15% minority floor at that θ.

## Question

v11 asks: “Is `Close[t+h]` far enough from `Close[t]` in ATR units?”

Label V2 asks: “What was the future **market behavior** over `t+1 … t+k`?”
Policy, not the label, turns that into LONG / SHORT / HOLD.

## Path window

Decision clock is the closed 5m bar at `t`. `High_t` and `Low_t` are known and
must not enter the target.

```
path = bars t+1 … t+k
k_10m = 2,  k_15m = 3,  k_30m = 6,  k_1h = 12
```

The last 12 five-minute rows are NaN (incomplete +1h). Use
`trim_label_v2_tail`. Live v11 still trims 24 bars via `trim_fusion_label_tail`.
2h remains an encoder input; it is not a Label V2 head.

## Core targets (stored once)

ATR is causal at `t` (14-period mean true range if the column is missing).
Rows with non-positive ATR are unlabeled (`NaN`), not divided by `1e-9`.

| Column | Formula |
| --- | --- |
| `{h}_ret` | `(Close[t+k] − Close[t]) / ATR[t]` |
| `{h}_long_mfe` | `max(0, (max(High[t+1:t+k]) − Close[t]) / ATR[t])` |
| `{h}_short_mfe` | `max(0, (Close[t] − min(Low[t+1:t+k])) / ATR[t])` |
| `{h}_long_mae` | `max(0, (Close[t] − min(Low[t+1 : t_long_mfe])) / ATR[t])` inclusive of the MFE bar |
| `{h}_short_mae` | `max(0, (max(High[t+1 : t_short_mfe]) − Close[t]) / ATR[t])` inclusive of the MFE bar |
| `{h}_persist` | `mean(sign(Close[t+j] − Close[t]))` for `j=1..k` (θ-free) |
| `{h}_t_long_mfe` | 1-based index of the first path max-high |
| `{h}_t_short_mfe` | 1-based index of the first path min-low |

Horizons: `h10m`, `h15m`, `h30m`, `h1h`. Leakage set: `label_v2_future_leak_cols()`.

All four excursion labels are **positive ATR units**. MAE is path-ordered (pain
to reach that side's MFE), so `short_*` is not `-long_*`. Same-bar opposite
wick counts as adverse. These are **not** the v8 percent-of-price labels and
**not** the positive adverse convention in `compute_path_edge`.

## Direction is a quantization of `R_h`

```
R_h >=  θ  → BULL  (2)
R_h <= −θ  → BEAR  (0)
else       → NEUTRAL (1)
```

θ grid: `0.25, 0.40, 0.50, 0.60, 0.75, 1.00`. Store `ret`; bin per θ. NEUTRAL is
a market state here, not `ignore_index`. Live v11 still ignores NEUTRAL.

## TP/SL is a diagnostic, not the primary target

Walk the path in bar order. Same-bar both-sides breach → `AMBIGUOUS` (3), never
a forced winner.

```
0 TP_FIRST
1 SL_FIRST
2 NEITHER
3 AMBIGUOUS
```

Evaluate LONG and SHORT from the same path. Grid (SL, TP) in ATR:

```
(0.5, 0.75), (0.75, 1.25), (1.0, 1.5), (1.5, 2.25), (2.0, 3.0)
```

Research duration brackets are included for disagreement stats:

```
h10m  SL 0.5 / TP 0.75
h15m  SL 0.75 / TP 1.25
h30m  SL 1.0 / TP 1.5
h1h   SL 1.5 / TP 2.25
```

Do not freeze the dataset to those multipliers.

Expectancy (ATR): enter BULL long / BEAR short, hold to first barrier or
horizon. `TP_FIRST` → `+tp`, `SL_FIRST` → `−sl`, `NEITHER` → `R_h`. Exclude
`AMBIGUOUS`.

## Persistence

- **Training diagnostic (stored):** θ-free mean sign.
- **Report-only:** fraction of path bars whose 3-class state matches the
  endpoint class at that θ.

Report both overlapping 5m samples and non-overlapping every-`k` samples.

## Code

- Constants: `feature_store/transformer_btcusd/contract.py` (`LABEL_V2_*`)
- Builder + report: `feature_store/transformer_btcusd/mtf_labels_v2.py`
- CLI: `python scripts/colab/report_label_v2.py --output export/label_v2/label_v2_report.json`
- Tests: `tests/unit/test_mtf_labels_v2.py`

Live files **not** modified for this research split: live `FUSION_HORIZON_*`
in `contract.py`, `fusion_policy.py`, `FusionModelNode`. Research ONNX export
and the Colab notebook follow v15 (`h10m`/`h15m`/`h30m`/`h1h` logits, no h2h).

## Go / no-go (per horizon, per θ)

A θ is acceptable only if all of the following hold:

1. No class rate `< 15%` (else flag; class weights are a later training choice).
2. `E[R | BULL] > 0`, `E[R | BEAR] < 0`, and their gap is at least θ.
3. Endpoint-vs-path disagreement (BEAR but long `TP_FIRST`, or BULL but short
   `TP_FIRST`) under the **live** bracket is `≥ 2%`. Below that, MFE/MAE are
   redundant with `R`.
4. `AMBIGUOUS` is not the majority of long `TP_FIRST + AMBIGUOUS` under the live
   bracket.
5. Mean θ-free persistence differs across classes by at least `0.10`.

Prefer θ = `0.50` among passing values. If h10m or h15m is `no-go` at every θ,
stop; do not train. **Stop before any Transformer retrain.**

## Latest validation run

Generated by `scripts/colab/report_label_v2.py` into
`export/label_v2/label_v2_report.json` (259,188 labeled 5m bars, 2024-04-09 to
2026-09-26). Overall gate: **go**. Frozen θ is **0.50 ATR** on `h10m`, `h15m`,
`h30m`, and `h1h`. At that θ, class mix stays above the 15% minority floor
(h10m NEUTRAL ~42%, BEAR/BULL ~29% each). Endpoint-vs-path disagreement is
~3–6% under research brackets. Diagnostics
(`export/fusion_diagnostics/report.json`) returned `later_direction_only`.
The current research trainer therefore trains direction CE only (path SmoothL1
weights 0, class weights off). Path heads remain on the ONNX graph. Direction
predictability (last-bar bake-off vs `best.pt` confusion) is a separate CPU
diagnostic; it does not retrain the fused model and does not promote live v11.
Path-edge regression (`--path-regression`) is the next last-bar diagnostic:
signed path quality, not 3-class direction. Live v11 is unchanged.

## Explicitly later

- Fused path SmoothL1 after the last-bar path-edge bake-off says the target is
  predictable (not another direction CE train)
- Inverse-frequency class weights
- Policy consuming `{P(dir), E[R], MFE, MAE, persist}`
- Quality-of-opportunity as a label
- Candlestick / chart-pattern targets
