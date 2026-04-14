"""
Paper Trade Logger - Dedicated log file for paper trades and P&L audit.

Writes each paper trade and position close to a rotating log file for
audit trail and P&L identification. Uses LOGS_ROOT when set (e.g. in Docker)
so logs persist under the mounted volume.
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
import structlog
import logging
from logging.handlers import RotatingFileHandler

from agent.core.audit_time import now_ist_iso, now_utc_iso

logger = structlog.get_logger()

# Use LOGS_ROOT when set (Docker: /logs), else project-relative logs/paper_trades
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOGS_ROOT = Path(os.environ.get("LOGS_ROOT", str(_PROJECT_ROOT / "logs")))
DEFAULT_LOG_DIR = _LOGS_ROOT / "paper_trades"
DEFAULT_LOG_FILE = "paper_trades.log"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5


class PaperTradeLogger:
    """Logs paper trades to a dedicated rotating file for P&L audit."""

    def __init__(self, log_dir: Optional[Path] = None, log_file: str = DEFAULT_LOG_FILE):
        """Initialize paper trade logger.

        Args:
            log_dir: Directory for log files (default: logs/paper_trades)
            log_file: Log file name
        """
        self.log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self.log_file = log_file
        self._handler: Optional[RotatingFileHandler] = None
        self._py_logger: Optional[logging.Logger] = None

    def _ensure_logger(self) -> logging.Logger:
        """Ensure file handler and logger are set up."""
        if self._py_logger is not None:
            return self._py_logger

        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / self.log_file

        self._handler = RotatingFileHandler(
            log_path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        self._handler.setFormatter(
            logging.Formatter("%(message)s")
        )

        self._py_logger = logging.getLogger("paper_trades")
        self._py_logger.setLevel(logging.INFO)
        self._py_logger.addHandler(self._handler)
        self._py_logger.propagate = False

        return self._py_logger

    def log_trade(
        self,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: float,
        fill_price: float,
        order_id: Optional[str] = None,
        position_id: Optional[str] = None,
        reasoning_chain_id: Optional[str] = None,
        usd_inr_rate: Optional[float] = None,
        trade_value_inr: Optional[float] = None,
        fees_inr: Optional[float] = None,
    ) -> None:
        """Log a paper trade execution.

        Args:
            trade_id: Unique trade identifier
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Trade quantity
            fill_price: Execution price
            order_id: Optional order ID
            position_id: Optional position ID
            reasoning_chain_id: Optional reasoning chain ID
        """
        try:
            py_logger = self._ensure_logger()
            ts_ist = now_ist_iso()
            ts_utc = now_utc_iso()
            line = (
                f"TRADE|{ts_ist}|{trade_id}|{symbol}|{side}|{quantity}|{fill_price}|"
                f"order_id={order_id or ''}|position_id={position_id or ''}|"
                f"reasoning_chain_id={reasoning_chain_id or ''}|"
                f"utc_time={ts_utc}|usd_inr_rate={usd_inr_rate if usd_inr_rate is not None else ''}|"
                f"trade_value_inr={trade_value_inr if trade_value_inr is not None else ''}|"
                f"fees_inr={fees_inr if fees_inr is not None else ''}\n"
            )
            py_logger.info(line.strip())
            try:
                from agent.core.signal_audit_md import append_paper_trade

                append_paper_trade(
                    trade_id=trade_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    fill_price=fill_price,
                    position_id=position_id,
                    reasoning_chain_id=reasoning_chain_id,
                )
            except Exception:
                pass
        except Exception as e:
            logger.warning(
                "paper_trade_logger_write_failed",
                error=str(e),
                trade_id=trade_id,
                symbol=symbol,
            )

    def log_position_close(
        self,
        position_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        pnl: float,
        exit_reason: str,
        fees_inr: Optional[float] = None,
        net_pnl_inr: Optional[float] = None,
        usd_inr_rate: Optional[float] = None,
        duration_seconds: Optional[float] = None,
        gross_pnl_usd: Optional[float] = None,
        usdinr_at_entry: Optional[float] = None,
        fx_pnl_inr: Optional[float] = None,
        pnl_pct_on_margin: Optional[float] = None,
        reasoning_chain_id: Optional[str] = None,
    ) -> None:
        """Log a position close for P&L tracking.

        Args:
            position_id: Position identifier
            symbol: Trading symbol
            side: BUY or SELL
            entry_price: Entry price
            exit_price: Exit price
            quantity: Position quantity
            pnl: Realized P&L
            exit_reason: Reason for exit (stop_loss, take_profit, signal_reversal)
        """
        try:
            py_logger = self._ensure_logger()
            ts_ist = now_ist_iso()
            ts_utc = now_utc_iso()
            chain_extra = (
                f"|reasoning_chain_id={reasoning_chain_id}"
                if reasoning_chain_id
                else ""
            )
            line = (
                f"CLOSE|{ts_ist}|{position_id}|{symbol}|{side}|{entry_price}|{exit_price}|"
                f"{quantity}|{pnl}|{exit_reason}{chain_extra}|utc_time={ts_utc}|"
                f"fees_inr={fees_inr if fees_inr is not None else ''}|"
                f"net_pnl_inr={net_pnl_inr if net_pnl_inr is not None else ''}|"
                f"usd_inr_rate_exit={usd_inr_rate if usd_inr_rate is not None else ''}|"
                f"usdinr_at_entry={usdinr_at_entry if usdinr_at_entry is not None else ''}|"
                f"gross_pnl_usd={gross_pnl_usd if gross_pnl_usd is not None else ''}|"
                f"fx_pnl_inr={fx_pnl_inr if fx_pnl_inr is not None else ''}|"
                f"pnl_pct_on_margin={pnl_pct_on_margin if pnl_pct_on_margin is not None else ''}|"
                f"duration_seconds={duration_seconds if duration_seconds is not None else ''}\n"
            )
            py_logger.info(line.strip())
            try:
                from agent.core.signal_audit_md import append_position_close

                append_position_close(
                    position_id=position_id,
                    symbol=symbol,
                    side=side,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    quantity=quantity,
                    pnl=pnl,
                    exit_reason=exit_reason,
                    net_pnl_inr=net_pnl_inr,
                    duration_seconds=duration_seconds,
                )
            except Exception:
                pass
        except Exception as e:
            logger.warning(
                "paper_trade_logger_close_failed",
                error=str(e),
                position_id=position_id,
                symbol=symbol,
            )


# Global instance
paper_trade_logger = PaperTradeLogger()
