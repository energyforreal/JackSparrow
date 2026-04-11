# AI signal and paper trading audit

Operational record for **model signals**, **risk / gate actions**, and **paper execution** (fills, fees, PnL, exit reasons). Use it alongside structured logs; the **paper trade pipe file** is the source of truth for notional, INR marks, and `reasoning_chain_id` on fills.

---

## Contents

| Section | Purpose |
|---------|---------|
| [How to use](#how-to-use-this-document) | What is live vs snapshot vs manual |
| [Realtime markdown stream](#realtime-markdown-stream) | Auto-appended `live_audit.md` |
| [Paper trading execution](#paper-trading-execution) | Authoritative paths, ledger tables, gate stats |
| [Reconciling approvals vs fills](#reconciling-risk-approvals-with-fills) | Why counts can differ |
| [Manual templates](#manual-templates) | Empty tables for ongoing notes |
| [Per-entry checklist](#per-entry-checklist) | Verification steps |
| [Sources and commands](#sources-and-commands) | Files, Docker, filters |
| [Session metadata](#session-metadata) | Snapshot fields |

---

## How to use this document

| Stream | Location | Updates |
|--------|----------|---------|
| **Live audit (markdown)** | `{LOGS_ROOT}/signal_audit/live_audit.md` | Every decision / reject / paper TRADE/CLOSE while the agent runs (`agent/core/signal_audit_md.py`). Toggle: `SIGNAL_AUDIT_MD_ENABLED`, `SIGNAL_AUDIT_MD_SUBPATH`. |
| **Paper ledger (pipe format)** | `{LOGS_ROOT}/paper_trades/paper_trades.log` | Each **`TRADE|`** and **`CLOSE|`** line; best for **trade_value_inr**, **fees**, **net_pnl_inr**, **exit_reason**, **duration_seconds**. |
| **Structlog JSON** | `logs/agent.log` or `docker logs jacksparrow-agent` | **decision_ready_handled**, **trading_entry_rejected**, **trading_handler_risk_approved_published**, **trade_executed**, **position_closed_successfully**. |
| **This file (`reference/…`)** | Git-friendly summary | Refreshed snapshots; not realtime. |

Timestamps are **UTC** unless a field explicitly says `local_time`.

---

## Realtime markdown stream

| | |
|--|--|
| **Path** | `{LOGS_ROOT}/signal_audit/live_audit.md` (default `LOGS_ROOT` = project `logs/`) |
| **Implementation** | `agent/core/signal_audit_md.py` |
| **Line tags** | `ai_signal`, `entry_rejected`, `risk_approved`, `paper_trade`, `position_close` |

---

## Paper trading execution

### Authoritative paths

| Data | Primary source | Secondary |
|------|----------------|-----------|
| Fill price, qty, `reasoning_chain_id`, INR notional, fees on entry | **`TRADE|`** in `paper_trades.log` | `trade_executed` in structlog (USD-centric, no chain id) |
| Realized PnL, exit reason, hold duration, net PnL INR, % on margin | **`CLOSE|`** in `paper_trades.log` | `position_closed`, `position_closed_successfully` |
| Why no trade | **trading_entry_rejected** | Same event in `live_audit.md` |

**Docker (agent container)** — typical paths: `/logs/paper_trades/paper_trades.log` if `LOGS_ROOT=/logs`, else under the app working directory. Example:

`docker exec jacksparrow-agent sh -c 'cat ${LOGS_ROOT:-/logs}/paper_trades/paper_trades.log'`

### Snapshot — structlog volume (`docker logs jacksparrow-agent --tail 25000`)

*Cutoff is log buffer size; increase `--tail` or omit it for a full export.*

| Field | Value |
|-------|--------|
| Container | `jacksparrow-agent` |
| Agent `session_id` | `17dc5a1a6d664120b3b1248896f043e0` |
| `decision_ready_handled` | 156 |
| `trading_entry_rejected` | 150 |
| `trading_handler_risk_approved_published` | 4 |

**Reject reasons (counts):** `daily_trade_cap` 76 · `hold_at_synthesis` 27 · `min_trade_gap` 30 · `debounce` 6 · `low_confidence_reject` 11

### Paper ledger excerpt — 2026-04-11 (from running container `paper_trades.log`)

Ground-truth rows for the current session’s April 11 activity: **TRADE** (opens/adds) and **CLOSE** (exits). Long floats rounded for readability.

**TRADE (entry legs)** — fill price is **actual paper fill** (may differ slightly from the `trading_handler_risk_approved_published` *entry_price* snapshot at approval time).

| Time (UTC) | Side | Qty | Fill (USD) | `order_id` | `reasoning_chain_id` | `trade_value_inr` @83 |
|------------|------|-----|--------------|------------|-------------------------|-------------------------|
| 2026-04-11 07:02:44 | SELL | 1.0 | 72353.95 | 3d2d2c08 | b099960d-6621-4aae-88cc-f53bad451bd4 | 6005.38 |
| 2026-04-11 09:22:17 | BUY | 1.0 | 73198.11 | d35355be | c57ac43c-da02-4fd5-8742-77d7954feb76 | 6075.44 |
| 2026-04-11 11:54:51 | SELL | 1.0 | 72567.80 | 7187ab5d | 471dbcce-6079-4d4c-a012-08c7c7ebbc8d | 6023.13 |

**CLOSE (exits)** — includes INR net, fees, gross USD, exit tag, duration.

| Exit (UTC) | `position_id` | Side | Entry → Exit (USD) | Gross PnL (USD) | Net PnL (INR) | Fees (INR) | Exit reason | Duration (s) | PnL % margin |
|------------|---------------|------|----------------------|-----------------|---------------|------------|-------------|--------------|--------------|
| 2026-04-11 11:54:06 | pos_d35355be | long | 73198.11 → 72711.63 | -0.4865 | -52.49 | 12.11 | signal_reversal | 9109.7 | -4.32% |
| 2026-04-11 11:54:51 | pos_d35355be | long | 73198.11 → 72728.39 | -0.4697 | -51.10 | 12.11 | market_close | 9154.3 | -4.21% |
| 2026-04-11 12:56:19 | pos_7187ab5d | short | 72567.80 → 73129.84 | -0.5620 | -58.74 | 12.09 | signal_reversal | 3688.5 | -4.88% |

**Note on two closes for `pos_d35355be`:** the log records a **signal_reversal** exit followed by a **market_close** on the same position id in quick succession—treat as the engine’s recorded lifecycle for that paper position; reconcile with `agent.log` if you need a single “canonical” close.

### Decision flow — sample rows (structlog, UTC)

Illustrative **decision → action** pairs (reject path). Full history: grep `docker logs` or `agent.log`.

| Time (UTC) | Signal | Conf. | Intended size | Action | Reason |
|------------|--------|-------|----------------|--------|--------|
| 2026-04-11 17:05:18 | SELL | 0.576 | 0.05 | rejected | daily_trade_cap |
| 2026-04-11 17:20:55 | SELL | 0.509 | 0.05 | rejected | low_confidence_reject |
| 2026-04-11 17:41:04 | HOLD | 0.489 | 0.0 | rejected | hold_at_synthesis |
| 2026-04-11 19:22:24 | BUY | 0.727 | 0.05 | rejected | daily_trade_cap |
| 2026-04-11 19:32:13 | STRONG_BUY | 0.714 | 0.1 | rejected | debounce |

### Risk-approved intents (same Docker window as snapshot)

| Time (UTC) | Side | Qty | Entry price (USD) | `event_id` |
|------------|------|-----|-------------------|------------|
| 2026-04-11 09:22:16 | BUY | 1.0 | 72862.5 | 041dd443-fa80-4a17-b66a-c7af84b6162c |
| 2026-04-11 10:11:21 | BUY | 1.0 | 72848.5 | 8738ddd6-c0d9-4a47-896a-1542ea686f8c |
| 2026-04-11 11:01:02 | BUY | 1.0 | 72795.0 | 7c2a716a-6104-4159-90d3-d9526dbf50b5 |
| 2026-04-11 11:54:51 | SELL | 1.0 | 72876.5 | 90cb2db8-7685-415b-9450-3fad4e57ce7c |

### Execution echo — structlog (same window)

**`trade_executed`**

| Time (UTC) | Side | Qty | `order_id` |
|------------|------|-----|------------|
| 2026-04-11 09:22:16 | buy | 1.0 | d35355be |
| 2026-04-11 11:54:51 | sell | 1.0 | 7187ab5d |

**`position_closed_successfully` (USD)**

| Exit (UTC) | Exit price | Gross PnL | Fees | Net PnL |
|------------|------------|-----------|------|---------|
| 2026-04-11 11:54:06 | 72711.63 | -0.4865 | 0.1459 | -0.6324 |
| 2026-04-11 11:54:51 | 72728.39 | -0.4697 | 0.1459 | -0.6157 |
| 2026-04-11 12:56:19 | 73129.84 | -0.5620 | 0.1457 | -0.7077 |

---

## Reconciling risk approvals with fills

- **`trading_handler_risk_approved_published`** counts *risk layer acceptance*; execution may still fail or debounce before a **`TRADE|`** line appears.
- In the sampled Docker window there were **4** risk approvals but only **two** `trade_executed` lines—earlier fills may sit **outside** `--tail 25000`, or some approvals did not reach a logged fill in that slice.
- Always tie **fills** to **`paper_trades.log`**: `order_id` on **`TRADE|`** matches short ids in **`trade_executed`** (e.g. `d35355be`).

---

## Manual templates

Use when you want a scratch pad not driven by automation.

**Signals and actions**

| Time (UTC) | Symbol | Signal | Confidence | Intended size | Action | Reason | `event_id` | Notes |
|------------|--------|--------|------------|---------------|--------|--------|------------|-------|
| | | | | | | | | |

**Position lifecycle** (prefer **`CLOSE|`** + **`TRADE|`** for IDs)

| `position_id` | Symbol | Side | Entry (UTC) | Qty | Entry px | Exit (UTC) | Exit px | Net PnL INR | Exit reason | Chain id |
|-----------------|--------|------|---------------|-----|----------|------------|---------|-------------|-------------|----------|
| | | | | | | | | | | |

---

## Per-entry checklist

- [ ] **`decision_ready_handled`** (or WebSocket `signal_update`) matches signal and confidence.
- [ ] If traded: **`TRADE|`** exists with **`reasoning_chain_id`**; optional match to **`trading_handler_risk_approved_published`** `event_id` via time/symbol.
- [ ] If flat: **`trading_entry_rejected`** reason documented (cap, debounce, hold, etc.).
- [ ] On exit: **`CLOSE|`** with **`position_id`** matching opening **`TRADE`**’s `pos_<order_id>` pattern when present.

---

## Sources and commands

### Structlog (`logs/agent.log` or Docker)

| `event` | Use |
|---------|-----|
| `decision_ready_handled` | Signal, confidence, `position_size`, `event_id` |
| `trading_handler_risk_approved_published` | Approved side, qty, entry price |
| `trading_entry_rejected` | Gate reason and diagnostics |
| `trade_executed` | Fill notification (short `order_id`) |
| `position_closed` / `position_closed_successfully` | USD PnL components |

**Docker:** `docker logs jacksparrow-agent --tail 50000` — JSON may span multiple lines; parse with a JSON stream decoder on the full string.

**PowerShell (filter):**

```powershell
docker logs jacksparrow-agent --tail 10000 2>&1 | Select-String "trading_handler_risk_approved_published|TRADE\||CLOSE\|"
```

### Paper ledger format (`paper_trade_logger`)

**`TRADE|`** — UTC time, `trade_id`, symbol, side, quantity, fill price, `order_id`, `position_id`, `reasoning_chain_id`, `usd_inr_rate`, `trade_value_inr`, `fees_inr`.

**`CLOSE|`** — exit UTC, `position_id`, symbol, side, entry/exit price, quantity, PnL (USD), `exit_reason`, `net_pnl_inr`, `fees_inr`, `gross_pnl_usd`, `duration_seconds`, `pnl_pct_on_margin`, FX fields when present.

### Backend / DB (optional)

- WebSocket **`signal_update`**: UI-only mirror of decisions; execution truth stays agent + paper file.
- DB **`TradeOutcomeRecord`** / `persist_trade_outcome_async`: long-term storage if enabled.

---

## Session metadata

| Field | Value (last snapshot) |
|-------|----------------------|
| Environment | `local` |
| Agent `session_id` | `17dc5a1a6d664120b3b1248896f043e0` |
| Docker log window | `--tail 25000` on 2026-04-12 export |
| Paper ledger source | `docker exec jacksparrow-agent` → `paper_trades.log` |
| Operator | |

---

*Document version: 2026-04-12 — reorganized; paper tables fed from container `paper_trades.log` + Docker structlog snapshot.*
