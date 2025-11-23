"""Telegram notification utilities for backend alerts."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
import structlog

from backend.core.config import settings

logger = structlog.get_logger()


class TelegramNotifier:
    """Send alert notifications to Telegram."""

    TELEGRAM_API_URL = "https://api.telegram.org"

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        """Create notifier with optional token overrides (useful for testing)."""
        self._bot_token = bot_token or settings.telegram_bot_token
        self._chat_id = chat_id or settings.telegram_chat_id

    @property
    def enabled(self) -> bool:
        """Return True when Telegram alerts are fully configured."""
        return bool(self._bot_token and self._chat_id)

    def _build_url(self) -> str:
        if not self._bot_token:
            raise ValueError("Telegram bot token is not configured.")
        return f"{self.TELEGRAM_API_URL}/bot{self._bot_token}/sendMessage"

    async def send_message(
        self,
        text: str,
        parse_mode: Optional[str] = "Markdown",
        disable_preview: bool = True,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send a generic message to the configured chat."""
        if not self.enabled:
            logger.info(
                "telegram_notifier_disabled",
                reason="missing_configuration",
            )
            return False

        payload: Dict[str, Any] = {
            "chat_id": self._chat_id,
            "text": text,
            "disable_notification": False,
            "disable_web_page_preview": disable_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if extra:
            payload.update(extra)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(self._build_url(), json=payload)
        except Exception as exc:  # pragma: no cover - network failure paths
            logger.error(
                "telegram_notification_failed",
                error=str(exc),
                payload=payload,
            )
            return False

        try:
            response_data = response.json()
        except ValueError:
            response_data = {"ok": False, "description": response.text}

        if response.status_code >= 400 or not response_data.get("ok", False):
            logger.warning(
                "telegram_notification_rejected",
                status_code=response.status_code,
                response=response_data,
            )
            return False

        logger.info("telegram_notification_sent")
        return True

    async def notify_trade_execution(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float],
        order_type: str,
        result: Dict[str, Any],
    ) -> bool:
        """Send a formatted trade execution alert."""
        text_lines = [
            "*✅ Trade Executed*",
            f"*Symbol:* `{symbol}`",
            f"*Side:* `{side}`",
            f"*Quantity:* `{quantity}`",
            f"*Order Type:* `{order_type}`",
        ]
        if price is not None:
            text_lines.append(f"*Price:* `{price}`")

        execution_id = result.get("order_id") or result.get("trade_id")
        if execution_id:
            text_lines.append(f"*Execution ID:* `{execution_id}`")

        pnl = result.get("pnl")
        if pnl is not None:
            text_lines.append(f"*PnL:* `{pnl}`")

        message = "\n".join(text_lines)
        return await self.send_message(message)


telegram_notifier = TelegramNotifier()

__all__ = ["TelegramNotifier", "telegram_notifier"]

