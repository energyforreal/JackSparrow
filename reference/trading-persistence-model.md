# Trading persistence model (JackSparrow / Trading Agent 2)

## Testnet (`TRADING_MODE=testnet`)

- **Authoritative ledger:** Delta Exchange margined positions and open orders.
- **PostgreSQL:** Trade/position rows are **not** written for testnet fills (`trade_persistence_service` skips with `testnet_exchange_ledger`).
- **On startup:** `position_restore` from DB is optional; **exchange reconcile** (`EXCHANGE_POSITION_RECONCILE_ENABLED`) is required for correct open legs.
- **In-memory:** `PositionManager` and `OrderManager` are hot paths; `data/agent_open_orders.json` snapshots open orders for crash recovery.

## Paper / non-testnet

- **Authoritative ledger:** PostgreSQL (`trades`, `positions`) via `agent_event_subscriber`.
- **On startup:** `POSITION_RESTORE_ON_STARTUP` loads OPEN rows into `PositionManager`.
- **Reconcile:** Still recommended when connected to a real exchange account.

## Kill switch

- **Env:** `TRADING_KILL_SWITCH=true` blocks all new entries (fail closed).
- **Runtime:** Admin `POST /api/v1/admin/agent/emergency-stop` flattens positions, sets context `emergency_stop`, publishes `EmergencyStopEvent`, transitions to `EMERGENCY_STOP`.

## Reconcile gate

When `BLOCK_ENTRIES_ON_RECONCILE_DIVERGENCE=true`, new entries are rejected until local and exchange position sets match after `reconcile_positions_with_exchange()`.
