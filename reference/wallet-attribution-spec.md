# Wallet attribution rules (JackSparrow)

Deterministic mapping from synced `wallet_transactions` rows to closed trades and `trade_outcomes` snapshots.

## Scope

- **In scope:** `commission`, `funding`, `commission_rebate` on perpetual products traded by the agent.
- **Out of scope (account-level only):** `deposit`, `withdrawal`, `trading_credits`, `referral_bonus`, `incident_compensation`.

## Commission

1. **Primary:** `metadata.order_id` on the wallet row matches a known agent fill (`js_` client order prefix or `agent_order_registry`).
2. **Fallback:** Same `product_id` and `occurred_at` within ±120 seconds of a recorded fill timestamp.
3. Attribute to the position active at `occurred_at` when unambiguous.

## Funding

1. Match `product_id` to the position's symbol/product.
2. Include rows where `occurred_at ∈ (position_opened_at, position_closed_at]` (open exclusive, close inclusive).
3. **Single open position per symbol (JackSparrow default):** allocate 100% of matching funding to that position.
4. Multiple open legs on same product: proportional to `abs(notional)` at funding time (future; not required for single-symbol MVP).

## Rebates

- `commission_rebate`: link via `meta_data` to originating commission when present; otherwise account-level (`attribution_status: unattributed`).

## Unmatched rows

- Persist in `wallet_transactions` with full `metadata`.
- Do not force-link to a trade; set `attribution_confidence: low` or `unattributed`.

## Snapshot output (`wallet_attribution`)

Attached to `trade_outcomes.metadata` on close:

| Field | Description |
|-------|-------------|
| `commission_usd` | Sum of attributed commission amounts |
| `funding_usd` | Sum of attributed funding amounts |
| `rebates_usd` | Sum of attributed rebates |
| `net_wallet_impact_usd` | Sum of all attributed wallet amounts |
| `attribution_confidence` | `high`, `medium`, `low`, `unattributed` |
| `linked_transaction_ids` | Delta `exchange_transaction_id` list |

## Confidence

- **high:** commission with `order_id` match, or funding with single open position window match
- **medium:** commission fallback time/product match
- **low / unattributed:** no deterministic match
