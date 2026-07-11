# Phase 3A.1 Gate Decision

Generated: 2026-07-11T12:31:34.394723+00:00
Source log: `data\investigation\agent_baseline_2026-07-11.log`

## Bucket histogram

| Bucket | Count | % |
|--------|------:|--:|
| B4 | 26 | 96.3% |
| B1 | 1 | 3.7% |

## Gate outcome

**Decision:** `proceed_3a2`

B4 share 96.3% exceeds 30% gate — policy semantics review justified.

## Next step

Proceed to 3A.2: enable `AGENT_POLICY_ALLOW_GATED_ML_ON_FLAT_HYPOTHESIS` on isolated testnet (48–72h).