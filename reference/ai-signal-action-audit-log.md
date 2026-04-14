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
| **Structlog JSON** | `logs/agent.log` or `docker logs jacksparrow-agent` | **decision_ready_handled**, **trading_entry_rejected**, **trading_handler_risk_approved_published**, **execution_order_fill_published**, **trading_execution_rejected**, **execution_failed**, **trade_executed**, **position_closed_successfully**, **position_close_skipped_already_closed**. |
| **This file (`reference/…`)** | Git-friendly summary | Refreshed snapshots; not realtime. |

**Timestamp policy:** Audit files use **IST (Asia/Kolkata)** as the **primary** clock: the second field of each **`TRADE|`** / **`CLOSE|`** line, and the bold time on each **`live_audit.md`** row. The same instant is repeated in UTC as **`utc_time=`** (pipe log) or **`utc=`** (markdown) for tooling and cross-system correlation. The agent Docker image sets **`TZ=Asia/Kolkata`**; timestamps are also computed with `zoneinfo.ZoneInfo("Asia/Kolkata")` in code (`agent/core/audit_time.py`).

### Artifact strategy (operational)

The project keeps **three layers** (no separate unified JSONL file in-repo):

1. **`paper_trades.log`** — quantitative truth for fills, fees, and realized PnL (`agent/core/paper_trade_logger.py`).
2. **`live_audit.md`** — narrative of AI signal → gates → paper echo (`agent/core/signal_audit_md.py`).
3. **Structlog** (`docker logs`, `agent.log`) — debugging and rich context.

A **single append-only JSONL** journal was considered optional; if added later, prefer lines like `{"ts_ist":"...","ts_utc":"...","event":"ai_signal|risk_approved|...","event_id":"..."}` written from the same hooks (see plan). Current analysis joins the pipe log and markdown on **`reasoning_chain_id`**, **`event_id`**, and time.

---

## Realtime markdown stream

| | |
|--|--|
| **Path** | `{LOGS_ROOT}/signal_audit/live_audit.md` (default `LOGS_ROOT` = project `logs/`) |
| **Implementation** | `agent/core/signal_audit_md.py` |
| **Timestamps** | Bold time = **IST**; each line includes `` utc=`...` `` for the same instant in UTC |
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

- **`trading_handler_risk_approved_published`** counts *risk layer acceptance*; execution may still fail before a **`TRADE|`** line appears. Every approval should leave a trace in structlog: **`execution_order_fill_published`** (same `event_id` as the approval), or **`trading_execution_rejected`** / **`execution_failed`** with `correlation_id` equal to that `event_id`.
- **Automated check (recommended):** from the repo root, after exporting `agent.log` JSON:

  `python tools/commands/reconcile_risk_approvals.py path/to/agent.log [path/to/paper_trades.log]`

  Exit code `1` lists approval `event_id`s with no matching outcome (orphan approvals). An optional second path prints a **`TRADE|`** count for sanity checks. See `docs/12-logging.md` (Error Analysis Tools).
- In a sampled Docker window, counts can still differ when **`--tail N`** truncates the buffer, or when earlier fills sit outside the window.
- Always tie **fills** to **`paper_trades.log`**: `order_id` on **`TRADE|`** matches short ids in **`trade_executed`** / **`execution_order_fill_published`** (e.g. `d35355be`).
- **Double `CLOSE|` on one position** should not occur: a second close logs **`position_close_skipped_already_closed`** and does not append another **`CLOSE|`** line (idempotent close in `agent/core/execution.py`).

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
- [ ] If traded: **`TRADE|`** exists with **`reasoning_chain_id`**; confirm **`execution_order_fill_published`** (or rejection/failure events) for the same `event_id` as **`trading_handler_risk_approved_published`**, or run **`reconcile_risk_approvals.py`** on exported logs.
- [ ] If flat: **`trading_entry_rejected`** reason documented (cap, debounce, hold, etc.).
- [ ] On exit: **`CLOSE|`** with **`position_id`** matching opening **`TRADE`**’s `pos_<order_id>` pattern when present.

---

## Sources and commands

### Retrieval (Docker and host)

- **Host (bind mounts):** `logs/paper_trades/paper_trades.log` and `logs/agent/signal_audit/live_audit.md` (when `LOGS_ROOT=/logs` in the agent container).
- **Copy out of a running container:**  
  `docker cp jacksparrow-agent:/logs/paper_trades/paper_trades.log ./backup/`  
  `docker cp jacksparrow-agent:/logs/signal_audit/live_audit.md ./backup/`
- **Print in container:**  
  `docker exec jacksparrow-agent sh -c 'cat ${LOGS_ROOT:-/logs}/paper_trades/paper_trades.log'`
- **Compose merge (dev):** `docker compose -f docker-compose.yml -f docker-compose.dev.yml config` — agent should list binds for `./logs/agent` → `/logs`, `./logs/paper_trades` → `/logs/paper_trades`, and source mounts.

### Structlog (`logs/agent.log` or Docker)

| `event` | Use |
|---------|-----|
| `decision_ready_handled` | Signal, confidence, `position_size`, `event_id` |
| `trading_handler_risk_approved_published` | Approved side, qty, entry price, `event_id` (correlate to execution below) |
| `trading_entry_rejected` | Gate reason and diagnostics |
| `execution_order_fill_published` | Successful fill path; **`event_id`** matches the risk approval |
| `trading_execution_rejected` | No fill: **`correlation_id`**, `stage`, `reason` (e.g. `execute_trade`, `invalid_price`) |
| `execution_failed` | Handler exception; **`correlation_id`**, `error` |
| `trade_executed` | Fill notification (short `order_id`) |
| `position_closed` / `position_closed_successfully` | USD PnL components |
| `position_close_skipped_already_closed` | Second close suppressed (idempotent) |

**Docker:** `docker logs jacksparrow-agent --tail 50000` — JSON may span multiple lines; parse with a JSON stream decoder on the full string.

**PowerShell (filter):**

```powershell
docker logs jacksparrow-agent --tail 10000 2>&1 | Select-String "trading_handler_risk_approved_published|TRADE\||CLOSE\|"
```

### Paper ledger format (`paper_trade_logger`)

**`TRADE|`** — **IST** time (field 2), `trade_id`, symbol, side, quantity, fill price, then key=value fields: `order_id`, `position_id`, `reasoning_chain_id`, **`utc_time=`** (UTC ISO), `usd_inr_rate`, `trade_value_inr`, `fees_inr`.

**`CLOSE|`** — **IST** time, `position_id`, symbol, side, entry/exit price, quantity, PnL (USD), `exit_reason`, **`utc_time=`**, `fees_inr`, `net_pnl_inr`, `usd_inr_rate_exit`, `usdinr_at_entry`, `gross_pnl_usd`, `fx_pnl_inr`, `pnl_pct_on_margin`, `duration_seconds`, etc., when present.

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

*Document version: 2026-04-12 — Reconciliation CLI and execution structlog events (`trading_execution_rejected`, `execution_failed`, idempotent close); IST-primary audit timestamps (`audit_time.py`); Docker retrieval notes; artifact strategy (three layers; optional JSONL deferred).*
