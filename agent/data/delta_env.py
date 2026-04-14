"""Log Delta REST vs WebSocket URL consistency (testnet vs prod, India vs global hints)."""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


def log_delta_env_mismatch_warnings(rest_url: str, ws_url: str) -> None:
    """Emit structured warnings when REST and WSS hosts look misaligned."""
    r = (rest_url or "").lower()
    w = (ws_url or "").lower()

    if ("testnet" in r) ^ ("testnet" in w):
        logger.warning(
            "delta_env_mismatch_warning",
            kind="testnet_mismatch",
            rest_url=rest_url,
            websocket_url=ws_url,
            message="REST and WEBSOCKET_URL disagree on testnet vs production hosts",
        )

    # One host is India-specific, the other is not (e.g. api.india vs global socket).
    if ("india" in r) ^ ("india" in w):
        if "delta" in r and "delta" in w:
            logger.warning(
                "delta_env_mismatch_warning",
                kind="india_global_mismatch",
                rest_url=rest_url,
                websocket_url=ws_url,
                message="REST and WEBSOCKET_URL may point at different Delta regions (India vs global)",
            )
