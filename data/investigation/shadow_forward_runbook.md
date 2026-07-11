# Forward Shadow Validation Runbook

**Purpose:** Out-of-sample (G6) validation before any 3A.2 policy flag enablement.

## Configuration

`LATENT_SHADOW_MODE=true` is set in `docker-compose.yml` (default via `.env.example`).

`AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` remains **false**.

## Protocol (48–72h)

**Collection started:** 2026-07-11 (agent recreated with `LATENT_SHADOW_MODE=true`)

1. Recreate agent container to pick up shadow mode:
   ```powershell
   docker compose up -d --force-recreate agent
   ```

2. Daily forensics:
   ```powershell
   python tools/commands/phase3_daily_forensics.py --workstream shadow
   ```

3. After 48h minimum, run shadow eval:
   ```powershell
   python tools/commands/shadow_eval.py --hours 48
   ```

4. Label shadow disagreements with realized returns:
   ```powershell
   python tools/commands/counterfactual_replay.py --hours 48 --economic
   ```
   Filter candidates where `policy_signal != shadow_signal` from telemetry `extra.latent_shadow`.

## G6 pass criteria

- Shadow-only entries (policy HOLD, shadow entry) have non-negative realized net EV over 48h window
- Shadow disagreement rate documented
- No increase in fee-dominated negative outcomes vs 30d replay baseline

## Current baseline (12h pre-shadow)

From `shadow_eval_report.json` (12h):
- Agreement rate: 97.8%
- Disagreements: 12 LONG policy vs HOLD shadow (the 4 ADX-blocked LONG cycles × duplicate telemetry rows)
- Shadow PnL proxy: 0 (all HOLD)

## Rollback

Set `LATENT_SHADOW_MODE=false` and recreate agent. No trading impact (shadow only).
