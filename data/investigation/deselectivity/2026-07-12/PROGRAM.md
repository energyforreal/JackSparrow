# De-selectivity program — optimize selectivity, preserve risk discipline

**Started:** 2026-07-12  
**Objective:** Remove unnecessary research-layer selectivity while keeping capital-protection controls intact.  
**Endpoint:** No single research-layer reject reason > **40%** of missed opportunities, **and** net expectancy ≥ baseline, **and** max DD ≤ baseline-window tolerance.

## Layers

| Layer | Role | Experiment? |
|-------|------|-------------|
| Thesis | Opportunity generation | Yes |
| Policy | Decision authority | Yes (higher risk) |
| Handler | Execution validation | Yes (after attribution) |
| Risk | Capital protection | **Frozen** |

## Adaptive rule

After each experiment: re-attribute reject mix → choose next bottleneck. Do **not** auto-advance A→B→C.

## Phase A (live now)

- Flag: `AGENT_THESIS_USE_HURST_V2=true`
- Window: 48–72h testnet
- Rollback: set flag `false`, restart agent

## Still off (do not enable with A)

- `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS`
- `V15_ADX_THESIS_AWARE_ENABLED`
- `AGENT_THESIS_NEUTRAL_MILD_TREND_ENABLED`
- Risk knobs (DD, size, margin)

## Daily

```powershell
python tools/commands/phase3_daily_forensics.py --workstream hurst_v2 --skip-rolling
# Add economic rolling only at T+48–72h gate (slow): omit --skip-rolling
```

Write `scorecard_dayN.md` against [`SCORECARD_BASELINE.md`](SCORECARD_BASELINE.md). See improvised artifacts: [`EARLY_READ.md`](EARLY_READ.md), [`scorecard_day0.md`](scorecard_day0.md), [`A_GATE_PROVISIONAL.md`](A_GATE_PROVISIONAL.md), [`ATTRIBUTION_NEXT.md`](ATTRIBUTION_NEXT.md), [`OFFLINE_BC.md`](OFFLINE_BC.md).

## Promotion (all required)

1. Replay EV ≥ baseline  
2. Testnet EV ≥ baseline  
3. DD ≤ tolerance  
4. Meaningful trend thesis fire increase (≥2× baseline or ≥5/24h)  
5. Negative controls (G1 / conditional handler / risk veto) within ±15%  
6. Ops healthy; no kill criteria  

Then mandatory attribution ([`ATTRIBUTION_NEXT.md`](ATTRIBUTION_NEXT.md)) before designing B/C/D — **do not auto-advance**.
