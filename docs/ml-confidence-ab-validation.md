# ML Confidence A/B Validation (Paper Trading)

This runbook compares baseline vs tuned confidence behavior without promoting to live trading.

## 1) Run baseline window

- Start stack with current settings.
- Collect at least 12-24 hours of paper-trading data.
- Keep artifacts:
  - Docker logs for `agent`
  - `prediction_audit` rows
  - `trade_outcomes` rows

## 2) Run tuned window

- Enable tuned configuration (same symbol/timeframes/session hours).
- Keep market window length comparable to baseline.
- Collect the same artifacts as baseline.

## 3) Compare signal mix and confidence buckets

```sql
-- prediction_audit metadata includes signal + reasoning context
SELECT
  metadata->>'signal' AS signal,
  COUNT(*) AS n,
  AVG(confidence) AS avg_conf
FROM prediction_audit
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY metadata->>'signal'
ORDER BY n DESC;
```

```sql
-- confidence bucket distribution
SELECT
  CASE
    WHEN confidence < 0.50 THEN 'lt_0.50'
    WHEN confidence < 0.55 THEN '0.50_0.55'
    WHEN confidence < 0.60 THEN '0.55_0.60'
    ELSE 'gte_0.60'
  END AS conf_bucket,
  COUNT(*) AS n
FROM prediction_audit
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY 1
ORDER BY 1;
```

## 4) Compare realized paper outcomes

```sql
SELECT
  COUNT(*) AS total_trades,
  AVG(CASE WHEN pnl > 0 THEN 1.0 ELSE 0.0 END) AS win_rate,
  SUM(pnl) AS net_pnl,
  AVG(pnl) AS avg_pnl
FROM trade_outcomes
WHERE closed_at >= NOW() - INTERVAL '24 hours';
```

## 5) HOLD root-cause checks from logs

Track these structured fields in agent logs:

- `reasoning_hold_exit.reason`
- `reasoning_hold_exit.hold_bucket`
- `reasoning_stage5_mtf_decision.hold_bucket`
- `trading_entry_rejected.reason`

Expected improvement after tuning:

- Lower `HOLD` share in active regimes.
- More confidence mass in `>=0.55` buckets for non-HOLD decisions.
- No material degradation in `win_rate` / `net_pnl`.

## 6) Promotion guardrails

Promote only if tuned run satisfies all:

- Non-HOLD precision improves or remains stable.
- HOLD-rate decreases in active sessions.
- Drawdown does not worsen beyond team threshold.
