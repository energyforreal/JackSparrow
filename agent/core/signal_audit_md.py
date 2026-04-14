"""
Realtime append-only markdown audit: AI decisions, trading actions, paper fills/closes.

Writes under LOGS_ROOT (see ``signal_audit_md_subpath`` in Settings), same root as
``logs/agent.log`` and ``logs/paper_trades/``. Thread-safe for concurrent handlers.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from agent.core.audit_time import now_ist_iso, now_utc_iso

logger = structlog.get_logger()

_lock = threading.Lock()
_session_banner_written = False

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _logs_root() -> Path:
    return Path(os.environ.get("LOGS_ROOT", str(_PROJECT_ROOT / "logs")))


def _audit_path() -> Path:
    from agent.core.config import settings

    sub = (
        getattr(settings, "signal_audit_md_subpath", None) or "signal_audit/live_audit.md"
    ).strip()
    return _logs_root() / sub


def _audit_ts_pair() -> tuple[str, str]:
    """IST (display) and UTC ISO strings for markdown lines."""
    return now_ist_iso(), now_utc_iso()


def _fmt_kv(d: Dict[str, Any], limit: int = 12) -> str:
    """Compact key=value for markdown line; skip huge nested blobs."""
    parts: list[str] = []
    n = 0
    for k, v in d.items():
        if n >= limit:
            parts.append("…")
            break
        if v is None or v == "":
            continue
        s = str(v)
        if len(s) > 120:
            s = s[:117] + "…"
        s = s.replace("|", "\\|").replace("\n", " ")
        parts.append(f"{k}={s}")
        n += 1
    return "; ".join(parts)


def _append_raw(line: str) -> None:
    global _session_banner_written
    try:
        from agent.core.config import settings

        if not getattr(settings, "signal_audit_md_enabled", True):
            return
    except Exception:
        return

    path = _audit_path()
    header = (
        "# AI signal and action audit (live)\n\n"
        "Auto-appended by the agent (`agent/core/signal_audit_md.py`). "
        "Timestamps are **IST (Asia/Kolkata)** in bold; `utc=` shows the same instant in UTC.\n\n"
        "---\n\n"
    )

    try:
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            exists_nonempty = path.exists() and path.stat().st_size > 0
            with path.open("a", encoding="utf-8") as f:
                if not exists_nonempty:
                    f.write(header)
                elif not _session_banner_written:
                    ist, utc = _audit_ts_pair()
                    f.write(
                        f"\n\n---\n\n## Process session {ist} (utc={utc})\n\n"
                    )
                    _session_banner_written = True
                f.write(line)
                if not exists_nonempty:
                    _session_banner_written = True
    except OSError as e:
        logger.warning("signal_audit_md_write_failed", error=str(e), path=str(path))


def append_decision_ready(
    *,
    symbol: Optional[str],
    signal: Optional[str],
    confidence: float,
    position_size: float,
    event_id: str,
    reasoning_chain_id: Optional[str] = None,
) -> None:
    ts_ist, ts_utc = _audit_ts_pair()
    line = (
        f"- **{ts_ist}** | `ai_signal` | `{signal or ''}` | "
        f"symbol={symbol or ''} | conf={confidence:.4f} | pos_size={position_size} | "
        f"event_id=`{event_id}` | utc=`{ts_utc}`"
    )
    if reasoning_chain_id:
        line += f" | chain=`{reasoning_chain_id}`"
    line += "\n"
    _append_raw(line)


def append_entry_rejected(
    *,
    reason: str,
    symbol: Optional[str],
    signal: Optional[str],
    event_id: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    ts_ist, ts_utc = _audit_ts_pair()
    tail = ""
    if extra:
        tail = " | " + _fmt_kv(extra)
    line = (
        f"- **{ts_ist}** | `entry_rejected` | reason=`{reason}` | "
        f"symbol={symbol or ''} | signal=`{signal or ''}` | event_id=`{event_id}` | "
        f"utc=`{ts_utc}`{tail}\n"
    )
    _append_raw(line)


def append_risk_approved(
    *,
    symbol: str,
    side: str,
    quantity: float,
    entry_price: float,
    event_id: str,
    reasoning_chain_id: Optional[str] = None,
) -> None:
    ts_ist, ts_utc = _audit_ts_pair()
    line = (
        f"- **{ts_ist}** | `risk_approved` | {side} | symbol={symbol} | "
        f"qty={quantity} | entry_price={entry_price} | event_id=`{event_id}` | utc=`{ts_utc}`"
    )
    if reasoning_chain_id:
        line += f" | chain=`{reasoning_chain_id}`"
    line += "\n"
    _append_raw(line)


def append_paper_trade(
    *,
    trade_id: str,
    symbol: str,
    side: str,
    quantity: float,
    fill_price: float,
    position_id: Optional[str] = None,
    reasoning_chain_id: Optional[str] = None,
) -> None:
    ts_ist, ts_utc = _audit_ts_pair()
    line = (
        f"- **{ts_ist}** | `paper_trade` | {side} | symbol={symbol} | "
        f"qty={quantity} | fill={fill_price} | trade_id=`{trade_id}` | utc=`{ts_utc}`"
    )
    if position_id:
        line += f" | position_id=`{position_id}`"
    if reasoning_chain_id:
        line += f" | chain=`{reasoning_chain_id}`"
    line += "\n"
    _append_raw(line)


def append_position_close(
    *,
    position_id: str,
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    quantity: float,
    pnl: float,
    exit_reason: str,
    net_pnl_inr: Optional[float] = None,
    duration_seconds: Optional[float] = None,
) -> None:
    ts_ist, ts_utc = _audit_ts_pair()
    line = (
        f"- **{ts_ist}** | `position_close` | {side} | symbol={symbol} | "
        f"qty={quantity} | entry={entry_price} | exit={exit_price} | "
        f"pnl_usd={pnl} | reason=`{exit_reason}` | position_id=`{position_id}` | utc=`{ts_utc}`"
    )
    if net_pnl_inr is not None:
        line += f" | net_pnl_inr={net_pnl_inr}"
    if duration_seconds is not None:
        line += f" | duration_s={duration_seconds}"
    line += "\n"
    _append_raw(line)
