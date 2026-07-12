# Phase A RUNBOOK — Hurst-v2 live testnet

**Start (UTC):** 2026-07-12 (agent recreate after `.env` enable)  
**Flag:** `AGENT_THESIS_USE_HURST_V2=true`  
**Frozen off:** flat-hyp ML, ADX thesis-aware, mild-trend  
**Window:** 48–72h then attribution

## Rollback

```powershell
# In .env: AGENT_THESIS_USE_HURST_V2=false
docker compose up -d agent
docker compose exec agent python -c "from agent.core.config import settings; print(settings.agent_thesis_use_hurst_v2)"
```

## Daily monitor

```powershell
python tools/commands/phase3_daily_forensics.py --workstream hurst_v2 --skip-rolling
# Funnel auto-runs for hurst_* workstreams; or:
python tools/commands/phase_a_funnel_from_telemetry.py --since 2026-07-12T10:21:37+00:00 `
  --out data/investigation/deselectivity/2026-07-12/funnel_post_a
```

Compare to `SCORECARD_BASELINE.md`. Write `scorecard_dayN.md` with **layered funnel** (thesis fires / quality_below / Gate5 / HOLD-after-fire). Pause if G1 / risk veto / conditional handler quality shift materially.

## After window

1. Promote or rollback per `PROGRAM.md`  
2. Re-run reject mix attribution  
3. Choose next experiment from **new** dominant research bottleneck (not auto-B)
