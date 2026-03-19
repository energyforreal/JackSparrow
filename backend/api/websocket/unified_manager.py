"""
Unified WebSocket Manager - Single communication layer with legacy envelope compatibility.

Consolidates all WebSocket communication into one manager. Emits backward-compatible
envelope (type, resource, data, timestamp, request_id) so the frontend reducer works
without changes. Supports command handling, subscriptions, Redis pub/sub, and agent client.
"""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List, Set, Any, Optional, Union
from datetime import datetime, date, timezone
from decimal import Decimal
import json
import asyncio
import time
import uuid
import structlog
import redis.asyncio as aioredis

from backend.core.redis import get_redis
from backend.core.config import settings
from backend.core.websocket_messages import (
    WebSocketEnvelope,
    create_health_update,
    create_agent_state_update,
    create_time_sync,
)
from backend.services.time_service import time_service
from backend.core.communication_logger import (
    log_websocket_message,
    generate_correlation_id,
    extract_correlation_id,
)

logger = structlog.get_logger()


def _json_default_encoder(obj: Any) -> Any:
    """JSON encoder for WebSocket payloads."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


def _sanitize_for_json(value: Any) -> Any:
    """Recursively convert complex types to JSON-serializable primitives."""
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(v) for v in value]
    if isinstance(value, (datetime, date, Decimal)):
        return _json_default_encoder(value)
    return value


def _envelope_to_legacy_dict(message: Union[Dict[str, Any], WebSocketEnvelope]) -> Dict[str, Any]:
    """Convert WebSocketEnvelope or dict to legacy broadcast dict (type, resource, data)."""
    if isinstance(message, WebSocketEnvelope):
        d = message.to_dict()
        # Ensure type/resource are strings for JSON
        if "type" in d and hasattr(d["type"], "value"):
            d["type"] = d["type"].value
        if "resource" in d and hasattr(d["resource"], "value"):
            d["resource"] = d["resource"].value
        return d
    return message


class UnifiedWebSocketManager:
    """
    Single WebSocket manager with legacy-compatible envelope.

    - Frontend clients: connect(is_agent=False), subscribe (ack "subscribed"), command handling.
    - Agent clients: connect(is_agent=True), handle_agent_client for agent_event routing.
    - All broadcasts use legacy shape: type, resource?, data, timestamp?, request_id?.
    """

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []
        self.agent_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
        self.connection_metadata: Dict[WebSocket, Dict[str, Any]] = {}
        self._instance_id = str(uuid.uuid4())[:8]
        self._redis_subscriber: Optional[aioredis.Redis] = None
        self._redis_publisher: Optional[aioredis.Redis] = None
        self._redis_task: Optional[asyncio.Task] = None
        self._time_sync_task: Optional[asyncio.Task] = None
        self._health_sync_task: Optional[asyncio.Task] = None
        self._agent_state_sync_task: Optional[asyncio.Task] = None
        self._redis_channel = "websocket:broadcast"
        self._last_signal: Optional[Dict[str, Any]] = None
        self._last_market_by_symbol: Dict[str, Dict[str, Any]] = {}
        self._last_agent_state: Optional[Dict[str, Any]] = None

    async def initialize(self) -> None:
        """Initialize Redis pub/sub and background sync tasks."""
        try:
            redis_check = await get_redis()
            if redis_check is None:
                logger.warning(
                    "unified_websocket_redis_unavailable",
                    message="Redis unavailable, WebSocket pub/sub disabled",
                )
                return
            self._redis_publisher = await get_redis()
            self._redis_subscriber = await aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
            )
            await self._redis_subscriber.ping()
            self._redis_task = asyncio.create_task(self._redis_listener())
            self._time_sync_task = asyncio.create_task(self._time_sync_loop())
            self._health_sync_task = asyncio.create_task(self._health_sync_loop())
            self._agent_state_sync_task = asyncio.create_task(self._agent_state_sync_loop())
            logger.info(
                "unified_websocket_initialized",
                instance_id=self._instance_id,
                redis_channel=self._redis_channel,
            )
        except Exception as e:
            logger.warning(
                "unified_websocket_init_warning",
                error=str(e),
                exc_info=True,
                message="WebSocket pub/sub disabled, using local broadcasting only",
            )
            if self._redis_subscriber:
                try:
                    await self._redis_subscriber.close()
                except Exception:
                    pass
                self._redis_subscriber = None

    async def cleanup(self) -> None:
        """Cancel background tasks and close Redis."""
        for task_name, task in [
            ("_redis_task", self._redis_task),
            ("_time_sync_task", self._time_sync_task),
            ("_health_sync_task", self._health_sync_task),
            ("_agent_state_sync_task", self._agent_state_sync_task),
        ]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._redis_subscriber:
            try:
                await self._redis_subscriber.close()
            except Exception as e:
                logger.warning("unified_websocket_cleanup_error", error=str(e))
        self._redis_subscriber = None
        self._redis_publisher = None
        self._redis_task = None
        self._time_sync_task = None
        self._health_sync_task = None
        self._agent_state_sync_task = None

    async def connect(self, websocket: WebSocket, is_agent: bool = False) -> None:
        """Accept WebSocket connection; send initial state for frontend clients."""
        await websocket.accept()
        self.connection_metadata[websocket] = {
            "connected_at": datetime.now(timezone.utc),
            "connection_id": str(uuid.uuid4()),
        }
        if is_agent:
            self.agent_connections.append(websocket)
            logger.info(
                "unified_websocket_agent_connected",
                total_agent_connections=len(self.agent_connections),
                total_frontend_connections=len(self.active_connections),
            )
            return
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()
        logger.info(
            "unified_websocket_connected",
            total_connections=len(self.active_connections),
        )
        # Send initial state in legacy envelope format
        try:
            if self._last_agent_state:
                state_data = dict(self._last_agent_state)
            else:
                from backend.services.agent_service import agent_service
                current_state = await agent_service.get_current_state()
                state_data = (
                    {
                        "state": current_state.get("state", "UNKNOWN"),
                        "timestamp": (
                            current_state.get("timestamp").isoformat()
                            if hasattr(current_state.get("timestamp"), "isoformat")
                            else current_state.get("timestamp", datetime.now(timezone.utc).isoformat())
                        ),
                        "reason": current_state.get("reason", ""),
                    }
                    if current_state
                    else {
                        "state": "UNKNOWN",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "reason": "",
                    }
                )
            self._last_agent_state = dict(state_data)
            await self.send_personal_message(
                websocket,
                {"type": "agent_update", "data": state_data},
            )
            if self._last_signal:
                # Only send cached signal if it is still fresh to avoid
                # showing very old signals when a new client connects.
                try:
                    ts_raw = self._last_signal.get("timestamp")
                    is_fresh = False
                    if isinstance(ts_raw, str):
                        try:
                            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                        except Exception:
                            ts = None
                    elif hasattr(ts_raw, "isoformat"):
                        ts = ts_raw  # type: ignore[assignment]
                    else:
                        ts = None

                    if ts is not None:
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()
                        # Treat signals older than 60 seconds as stale for
                        # initial snapshot purposes.
                        is_fresh = age_seconds <= 60

                    if is_fresh:
                        await self.send_personal_message(
                            websocket,
                            {
                                "type": "data_update",
                                "resource": "signal",
                                "data": self._last_signal,
                            },
                        )
                except Exception:
                    # If freshness calculation fails, skip sending cached signal
                    # rather than risking a misleading stale value.
                    pass
            market_snapshot = (
                self._last_market_by_symbol.get("BTCUSD")
                or (next(iter(self._last_market_by_symbol.values()), None) if self._last_market_by_symbol else None)
            )
            if market_snapshot:
                await self.send_personal_message(
                    websocket,
                    {"type": "data_update", "resource": "market", "data": market_snapshot},
                )
            # Push health snapshot immediately so frontend does not wait for poll interval
            from backend.core.database import AsyncSessionLocal
            from backend.api.routes.health import check_overall_health
            async with AsyncSessionLocal() as db:
                health_data = await check_overall_health(db)
            if health_data:
                # Normalize for frontend: ensure status key (overall_status fallback in Phase 2)
                health_payload = dict(health_data)
                if "timestamp" in health_payload and hasattr(health_payload["timestamp"], "isoformat"):
                    health_payload["timestamp"] = health_payload["timestamp"].isoformat()
                await self.send_personal_message(
                    websocket,
                    {
                        "type": "system_update",
                        "resource": "health",
                        "data": health_payload,
                    },
                )
        except Exception as e:
            logger.debug(
                "unified_websocket_initial_state_failed",
                error=str(e),
                message="Failed to send initial state, will be sent on next sync",
            )

    async def disconnect(self, websocket: WebSocket, is_agent: bool = False) -> None:
        """Remove connection from pools."""
        if is_agent:
            if websocket in self.agent_connections:
                self.agent_connections.remove(websocket)
            logger.info(
                "unified_websocket_agent_disconnected",
                total_agent_connections=len(self.agent_connections),
                total_frontend_connections=len(self.active_connections),
            )
        else:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
            if websocket in self.subscriptions:
                del self.subscriptions[websocket]
            logger.info(
                "unified_websocket_disconnected",
                total_connections=len(self.active_connections),
            )
        if websocket in self.connection_metadata:
            del self.connection_metadata[websocket]

    async def subscribe(self, websocket: WebSocket, channels: List[str]) -> None:
        """Subscribe client to channels; ack with type 'subscribed' for frontend compatibility."""
        if websocket not in self.subscriptions:
            logger.warning(
                "unified_websocket_subscribe_failed",
                channels=channels,
                message="WebSocket not in subscriptions dictionary",
            )
            return
        self.subscriptions[websocket].update(channels)
        logger.info(
            "unified_websocket_subscribed",
            channels=channels,
            total_subscriptions=len(self.subscriptions[websocket]),
        )
        await self.send_personal_message(websocket, {"type": "subscribed", "channels": channels})

    async def unsubscribe(self, websocket: WebSocket, channels: List[str]) -> None:
        """Unsubscribe client from channels."""
        if websocket in self.subscriptions:
            self.subscriptions[websocket].difference_update(channels)
            await self.send_personal_message(websocket, {"type": "unsubscribed", "channels": channels})

    async def send_personal_message(
        self,
        websocket: WebSocket,
        message: Dict[str, Any],
        is_agent: bool = False,
    ) -> None:
        """Send legacy-format message to one client."""
        try:
            safe = _sanitize_for_json(message)
            correlation_id = extract_correlation_id(message)
            log_websocket_message(
                direction="outbound",
                message_type=message.get("type", "unknown"),
                resource=message.get("resource"),
                correlation_id=correlation_id,
                target="agent" if is_agent else "frontend",
                payload=safe,
            )
            await websocket.send_json(safe)
        except Exception as e:
            logger.error(
                "unified_websocket_send_error",
                error=str(e),
                exc_info=True,
            )
            await self.disconnect(websocket, is_agent=is_agent)

    async def broadcast(
        self,
        message: Union[Dict[str, Any], WebSocketEnvelope],
        channel: Optional[str] = None,
    ) -> None:
        """Broadcast in legacy envelope format (type, resource, data). Update caches and Redis."""
        if message is None:
            logger.warning("unified_websocket_ignoring_empty_broadcast")
            return
        message_dict = _envelope_to_legacy_dict(message)
        if "server_timestamp" not in message_dict:
            time_info = time_service.get_time_info()
            message_dict["server_timestamp"] = time_info["server_time"]
            message_dict["server_timestamp_ms"] = time_info["timestamp_ms"]
        try:
            msg_type = message_dict.get("type")
            resource = message_dict.get("resource")
            data = message_dict.get("data")
            msg_type_str = getattr(msg_type, "value", msg_type)
            resource_str = getattr(resource, "value", resource)
            if msg_type_str == "data_update":
                if resource_str == "signal" and isinstance(data, dict):
                    self._last_signal = dict(data)
                elif resource_str == "market" and isinstance(data, dict) and data.get("symbol"):
                    self._last_market_by_symbol[data["symbol"]] = dict(data)
            elif msg_type_str == "agent_update" and isinstance(data, dict):
                self._last_agent_state = dict(data)
        except Exception as e:
            logger.debug("unified_websocket_cache_update_failed", error=str(e))
        safe_message = _sanitize_for_json(message_dict)
        correlation_id = extract_correlation_id(message_dict)
        log_websocket_message(
            direction="outbound",
            message_type=message_dict.get("type", "broadcast"),
            resource=message_dict.get("resource"),
            correlation_id=correlation_id,
            target="frontend",
            payload=safe_message,
        )
        broadcast_payload = {
            "instance_id": self._instance_id,
            "channel": channel,
            "message": safe_message,
            "timestamp": time.time(),
        }
        if self._redis_publisher:
            try:
                await self._redis_publisher.publish(
                    self._redis_channel,
                    json.dumps(broadcast_payload, default=_json_default_encoder),
                )
            except Exception as e:
                logger.warning(
                    "unified_websocket_redis_publish_failed",
                    error=str(e),
                    message="Falling back to local broadcast only",
                )
        await self._broadcast_local(safe_message, channel)

    async def _broadcast_local(self, message: Dict[str, Any], channel: Optional[str] = None) -> None:
        """Send message to all local frontend connections (optionally filtered by channel)."""
        if not self.active_connections:
            return
        disconnected: List[WebSocket] = []
        for ws in self.active_connections:
            try:
                if channel and ws in self.subscriptions and self.subscriptions[ws]:
                    if channel not in self.subscriptions[ws]:
                        continue
                await ws.send_json(message)
            except WebSocketDisconnect:
                disconnected.append(ws)
            except Exception as e:
                logger.error("unified_websocket_broadcast_failed", error=str(e), exc_info=True)
                disconnected.append(ws)
        for ws in disconnected:
            await self.disconnect(ws, is_agent=False)

    async def _redis_listener(self) -> None:
        """Forward Redis pub/sub messages to local connections."""
        if not self._redis_subscriber:
            return
        try:
            pubsub = self._redis_subscriber.pubsub()
            await pubsub.subscribe(self._redis_channel)
            logger.info("unified_websocket_redis_listener_started", channel=self._redis_channel)
            while True:
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=1.0,
                    )
                    if msg and msg.get("type") == "message":
                        try:
                            data = json.loads(msg.get("data", "{}"))
                            if data.get("instance_id") != self._instance_id:
                                await self._broadcast_local(
                                    data.get("message", {}),
                                    data.get("channel"),
                                )
                        except (json.JSONDecodeError, KeyError) as e:
                            logger.warning("unified_websocket_redis_decode_error", error=str(e))
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error("unified_websocket_redis_listener_error", error=str(e), exc_info=True)
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("unified_websocket_redis_listener_cancelled")
            raise
        except Exception as e:
            logger.error("unified_websocket_redis_listener_fatal", error=str(e), exc_info=True)

    async def handle_command(self, websocket: WebSocket, command_data: Dict[str, Any]) -> None:
        """Handle WebSocket command (get_health, get_portfolio, get_agent_status, etc.)."""
        command = command_data.get("command")
        request_id = command_data.get("request_id", generate_correlation_id())
        parameters = command_data.get("parameters", {})
        try:
            from backend.core.communication_logger import log_frontend_command
            log_frontend_command(direction="inbound", command=command, correlation_id=request_id, payload=parameters)
            response_data = await self._execute_command(command, parameters)
            response_data["request_id"] = request_id
            response_data["command"] = command
            response_data.setdefault("type", "response")
            await self.send_personal_message(websocket, response_data)
        except Exception as e:
            logger.error(
                "unified_websocket_command_error",
                command=command,
                request_id=request_id,
                error=str(e),
                exc_info=True,
            )
            await self.send_personal_message(
                websocket,
                {
                    "type": "response",
                    "request_id": request_id,
                    "command": command,
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

    async def _execute_command(self, command: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single command and return response dict (type, success, data, timestamp)."""
        if command == "predict":
            from backend.services.agent_service import agent_service
            prediction_result = await agent_service.get_prediction(
                symbol=parameters.get("symbol", "BTCUSD"),
                context=parameters.get("context", {}),
            )
            return {
                "type": "response",
                "success": prediction_result is not None,
                "data": prediction_result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        if command == "execute_trade":
            from backend.services.agent_service import agent_service
            trade_result = await agent_service.execute_trade(
                symbol=parameters.get("symbol"),
                side=parameters.get("side"),
                quantity=parameters.get("quantity"),
                order_type=parameters.get("order_type", "MARKET"),
                price=parameters.get("price"),
                stop_loss=parameters.get("stop_loss"),
                take_profit=parameters.get("take_profit"),
            )
            return {
                "type": "response",
                "success": trade_result is not None,
                "data": trade_result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        if command == "get_portfolio":
            from backend.services.portfolio_service import portfolio_service
            from backend.core.database import AsyncSessionLocal
            from backend.core.config import settings
            async with AsyncSessionLocal() as db:
                try:
                    portfolio_data = await portfolio_service.get_portfolio_summary(db)
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            if portfolio_data:
                try:
                    portfolio_data = portfolio_service.serialize_portfolio_summary(portfolio_data)
                except ValueError:
                    initial_balance = float(getattr(settings, "initial_balance", 10000.0))
                    portfolio_data = {
                        "total_value": initial_balance,
                        "available_balance": initial_balance,
                        "open_positions": 0,
                        "total_unrealized_pnl": 0,
                        "total_realized_pnl": 0,
                        "positions": [],
                        "timestamp": time_service.get_time_info()["server_time"],
                    }
            else:
                initial_balance = float(getattr(settings, "initial_balance", 10000.0))
                portfolio_data = {
                    "total_value": initial_balance,
                    "available_balance": initial_balance,
                    "open_positions": 0,
                    "total_unrealized_pnl": 0,
                    "total_realized_pnl": 0,
                    "positions": [],
                    "timestamp": time_service.get_time_info()["server_time"],
                }
            return {
                "type": "response",
                "success": True,
                "data": portfolio_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        if command == "get_positions":
            from backend.core.database import Position, PositionStatus, AsyncSessionLocal
            from sqlalchemy import select, desc
            from backend.api.models.responses import PositionResponse
            async with AsyncSessionLocal() as db:
                try:
                    query = select(Position).where(Position.status == PositionStatus.OPEN).order_by(
                        desc(Position.opened_at)
                    ).limit(100)
                    result = await db.execute(query)
                    positions = result.scalars().all()
                    positions_data = [
                        PositionResponse.model_validate(pos).model_dump(mode="json") for pos in positions
                    ]
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            return {
                "type": "response",
                "success": True,
                "data": positions_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        if command == "get_trades":
            from backend.core.database import Trade, AsyncSessionLocal
            from sqlalchemy import select, desc
            from backend.api.models.responses import TradeResponse
            async with AsyncSessionLocal() as db:
                try:
                    query = select(Trade).order_by(desc(Trade.executed_at)).limit(100)
                    result = await db.execute(query)
                    trades = result.scalars().all()
                    trades_data = [
                        TradeResponse.model_validate(t).model_dump(mode="json") for t in trades
                    ]
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            return {
                "type": "response",
                "success": True,
                "data": trades_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        if command == "get_health":
            from backend.api.routes.health import check_overall_health
            from backend.core.database import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                try:
                    health_data = await check_overall_health(db)
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
            if health_data and "timestamp" in health_data and hasattr(health_data["timestamp"], "isoformat"):
                health_data = dict(health_data)
                health_data["timestamp"] = health_data["timestamp"].isoformat()
            return {
                "type": "response",
                "success": True,
                "data": health_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        if command == "get_agent_status":
            from backend.services.agent_service import agent_service
            status_data = await agent_service.get_agent_status()
            return {
                "type": "response",
                "success": status_data is not None,
                "data": status_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        raise ValueError(f"Unknown command: {command}")

    async def handle_client(self, websocket: WebSocket) -> None:
        """Handle frontend client messages: subscribe (ack 'subscribed'), command, get_state, get_agent_state."""
        try:
            while True:
                data = await websocket.receive_json()
                correlation_id = extract_correlation_id(data)
                log_websocket_message(
                    direction="inbound",
                    message_type=data.get("action", "unknown"),
                    correlation_id=correlation_id,
                    target="frontend",
                    payload=data,
                )
                action = data.get("action")
                if action == "subscribe":
                    channels = data.get("channels", [])
                    await self.subscribe(websocket, channels)
                elif action == "unsubscribe":
                    channels = data.get("channels", [])
                    await self.unsubscribe(websocket, channels)
                elif action == "command":
                    await self.handle_command(websocket, data)
                elif action == "get_state":
                    await self.send_personal_message(
                        websocket,
                        {
                            "type": "state",
                            "data": {
                                "connections": len(self.active_connections),
                                "subscribed_channels": list(self.subscriptions.get(websocket, set())),
                            },
                        },
                    )
                elif action == "get_agent_state":
                    try:
                        from backend.services.agent_service import agent_service
                        current_state = await agent_service.get_current_state()
                        state_data = (
                            {
                                "state": current_state.get("state", "UNKNOWN"),
                                "timestamp": (
                                    current_state.get("timestamp").isoformat()
                                    if hasattr(current_state.get("timestamp"), "isoformat")
                                    else current_state.get("timestamp", datetime.now(timezone.utc).isoformat())
                                ),
                                "reason": current_state.get("reason", ""),
                            }
                            if current_state
                            else {
                                "state": "UNKNOWN",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "reason": "Agent state unavailable",
                            }
                        )
                        await self.send_personal_message(
                            websocket,
                            {"type": "agent_update", "data": state_data},
                        )
                    except Exception as e:
                        logger.warning("unified_websocket_get_agent_state_error", error=str(e))
                        await self.send_personal_message(
                            websocket,
                            {
                                "type": "error",
                                "message": f"Failed to get agent state: {str(e)}",
                            },
                        )
                else:
                    await self.send_personal_message(
                        websocket,
                        {"type": "error", "message": f"Unknown action: {action}"},
                    )
        except WebSocketDisconnect:
            await self.disconnect(websocket, is_agent=False)
        except Exception as e:
            logger.error("unified_websocket_client_handler_error", error=str(e), exc_info=True)
            await self.disconnect(websocket, is_agent=False)

    async def handle_agent_client(self, websocket: WebSocket) -> None:
        """Handle agent WebSocket: route agent_event to agent_event_subscriber."""
        try:
            while True:
                data = await websocket.receive_json()
                correlation_id = extract_correlation_id(data)
                log_websocket_message(
                    direction="inbound",
                    message_type=data.get("type", "unknown"),
                    resource=data.get("event_type"),
                    correlation_id=correlation_id,
                    target="agent",
                    payload=data,
                )
                msg_type = data.get("type")
                if msg_type == "agent_event":
                    event_type = data.get("event_type")
                    payload = data.get("payload", {})
                    from backend.services.agent_event_subscriber import agent_event_subscriber
                    await agent_event_subscriber._handle_event(event_type, payload, event_dict=data)
                    if data.get("request_ack"):
                        ack_message = {
                            "type": "ack",
                            "event_id": data.get("event_id"),
                            "correlation_id": correlation_id or generate_correlation_id(),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        await self.send_personal_message(websocket, ack_message, is_agent=True)
                elif msg_type == "ping":
                    await self.send_personal_message(
                        websocket,
                        {
                            "type": "pong",
                            "correlation_id": correlation_id or generate_correlation_id(),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        is_agent=True,
                    )
                else:
                    logger.warning("unified_websocket_agent_unknown_message_type", msg_type=msg_type)
        except WebSocketDisconnect:
            await self.disconnect(websocket, is_agent=True)
        except Exception as e:
            logger.error("unified_websocket_agent_handler_error", error=str(e), exc_info=True)
            await self.disconnect(websocket, is_agent=True)

    async def _time_sync_loop(self) -> None:
        """Periodic time sync broadcast in legacy envelope."""
        try:
            while True:
                await asyncio.sleep(30)
                if not self.active_connections:
                    continue
                time_info = time_service.get_time_info()
                sync_message = create_time_sync(time_info)
                await self.broadcast(sync_message, channel="system_update")
        except asyncio.CancelledError:
            logger.info("unified_websocket_time_sync_cancelled")
            raise
        except Exception as e:
            logger.error("unified_websocket_time_sync_error", error=str(e), exc_info=True)

    async def _health_sync_loop(self) -> None:
        """Single health broadcast loop using check_overall_health (one canonical source)."""
        try:
            while True:
                await asyncio.sleep(60)
                if not self.active_connections:
                    continue
                try:
                    from backend.api.routes.health import check_overall_health
                    from backend.core.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as db:
                        health_data = await check_overall_health(db)
                    if health_data and "timestamp" in health_data and hasattr(health_data["timestamp"], "isoformat"):
                        health_data = dict(health_data)
                        health_data["timestamp"] = health_data["timestamp"].isoformat()
                    health_message = create_health_update(health_data)
                    await self.broadcast(health_message, channel="system_update")
                except Exception as health_error:
                    logger.warning(
                        "unified_websocket_health_sync_error",
                        error=str(health_error),
                        message="Failed to broadcast health update, will retry on next cycle",
                    )
        except asyncio.CancelledError:
            logger.info("unified_websocket_health_sync_cancelled")
            raise
        except Exception as e:
            logger.error("unified_websocket_health_sync_loop_error", error=str(e), exc_info=True)

    async def _agent_state_sync_loop(self) -> None:
        """Periodic agent state broadcast in legacy envelope."""
        try:
            while True:
                await asyncio.sleep(30)
                if not self.active_connections:
                    continue
                try:
                    from backend.services.agent_service import agent_service
                    current_state = await agent_service.get_current_state()
                    if current_state:
                        state_data = {
                            "state": current_state.get("state", "UNKNOWN"),
                            "timestamp": (
                                current_state.get("timestamp").isoformat()
                                if hasattr(current_state.get("timestamp"), "isoformat")
                                else current_state.get("timestamp", datetime.now(timezone.utc).isoformat())
                            ),
                            "reason": current_state.get("reason", ""),
                        }
                        self._last_agent_state = dict(state_data)
                        state_message = create_agent_state_update(state_data)
                        await self.broadcast(state_message, channel="agent_update")
                except Exception as e:
                    logger.warning(
                        "unified_websocket_agent_state_sync_error",
                        error=str(e),
                        message="Failed to sync agent state, will retry on next cycle",
                    )
        except asyncio.CancelledError:
            logger.info("unified_websocket_agent_state_sync_cancelled")
            raise
        except Exception as e:
            logger.error(
                "unified_websocket_agent_state_sync_loop_error",
                error=str(e),
                exc_info=True,
            )


unified_websocket_manager = UnifiedWebSocketManager()
