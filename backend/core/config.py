"""
Configuration management for backend service.

Handles environment variable loading, validation, and default values.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
import os
from pydantic import Field, field_validator, model_validator

# Env-file split (single root location for all services):
#   - .env.example (committed): non-secret defaults, thresholds, feature flags.
#   - .env          (gitignored): secrets only (DB password, Delta keys, JWT, API_KEY, ...).
# Pydantic Settings loads the tuple in order; later files override earlier ones,
# so secrets in .env always win over placeholders in .env.example.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT_ENV_PATH = _PROJECT_ROOT / ".env"
ROOT_ENV_EXAMPLE_PATH = _PROJECT_ROOT / ".env.example"


def _root_env_files() -> tuple[str, ...] | None:
    """Return existing env files in load order (.env.example, then .env)."""
    paths: list[str] = []
    if ROOT_ENV_EXAMPLE_PATH.exists():
        paths.append(str(ROOT_ENV_EXAMPLE_PATH))
    if ROOT_ENV_PATH.exists():
        paths.append(str(ROOT_ENV_PATH))
    return tuple(paths) if paths else None


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=_root_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
        protected_namespaces=("settings_",),
    )
    
    # Database
    database_url: str = Field(
        ...,
        env=("DATABASE_URL", "database_url"),
        description="PostgreSQL database connection URL"
    )
    
    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379",
        env="REDIS_URL",
        description="Redis connection URL"
    )
    redis_required: bool = Field(
        default=False,
        env="REDIS_REQUIRED",
        description="Require Redis connectivity during startup"
    )
    redis_max_connections: int = Field(
        default=12,
        env="REDIS_MAX_CONNECTIONS",
        description="Max connections in Redis async pool (command workloads)",
    )
    
    # Delta Exchange API
    delta_exchange_api_key: str = Field(
        ...,
        env=("DELTA_EXCHANGE_API_KEY", "DELTA_API_KEY", "delta_api_key"),
        description="Delta Exchange API key"
    )
    delta_exchange_api_secret: str = Field(
        ...,
        env=("DELTA_EXCHANGE_API_SECRET", "DELTA_API_SECRET", "delta_api_secret"),
        description="Delta Exchange API secret"
    )
    delta_exchange_base_url: str = Field(
        default="https://api.india.delta.exchange",
        env=("DELTA_EXCHANGE_BASE_URL", "DELTA_API_URL", "delta_api_url"),
        description="Delta Exchange API base URL"
    )
    
    # Agent Communication
    agent_command_queue: str = Field(
        default="agent_commands",
        env="AGENT_COMMAND_QUEUE",
        description="Redis queue for agent commands"
    )
    agent_response_queue: str = Field(
        default="agent_responses",
        env="AGENT_RESPONSE_QUEUE",
        description="Redis queue for agent responses"
    )
    agent_websocket_url: str = Field(
        # Docker: use service name "agent" and AGENT_WS_PORT (8003). Local dev: set AGENT_WS_URL.
        default="ws://agent:8003",
        env="AGENT_WS_URL",
        description="Agent WebSocket URL for backend client connections"
    )
    use_agent_websocket: bool = Field(
        default=True,
        env="USE_AGENT_WEBSOCKET",
        description="Use WebSocket for agent communication (fallback to Redis queue if False or unavailable)"
    )
    agent_redis_fallback_when_ws_connected: bool = Field(
        default=True,
        env="AGENT_REDIS_FALLBACK_WHEN_WS_CONNECTED",
        description="When False, do not enqueue Redis commands if outbound agent WebSocket was connected (avoids duplicate delivery)",
    )
    agent_command_queue_max_depth: int = Field(
        default=5000,
        env="AGENT_COMMAND_QUEUE_MAX_DEPTH",
        ge=0,
        description="Skip LPUSH when agent command queue length exceeds this (0 disables)",
    )
    
    # Feature Server
    feature_server_url: str = Field(
        default="http://localhost:8002",
        env="FEATURE_SERVER_URL",
        description="MCP Feature Server URL"
    )

    # Model serving (dedicated service or agent feature server predict endpoint)
    model_serving_url: str = Field(
        default="",
        env="MODEL_SERVING_URL",
        description="Model serving base URL (health, predict). If empty, uses FEATURE_SERVER_URL."
    )

    # Prediction cache TTL (seconds); 0 disables cache
    prediction_cache_ttl: int = Field(
        default=0,
        env="PREDICTION_CACHE_TTL",
        description="Redis TTL for prediction response cache (0 to disable)"
    )

    # Model health heartbeat TTL (seconds)
    model_health_ttl: int = Field(
        default=30,
        env="MODEL_HEALTH_TTL",
        description="Redis TTL for model-serving health heartbeat"
    )
    
    # Vector Database (Optional)
    qdrant_url: Optional[str] = Field(
        default=None,
        env="QDRANT_URL",
        description="Qdrant vector database URL"
    )
    qdrant_api_key: Optional[str] = Field(
        default=None,
        env="QDRANT_API_KEY",
        description="Qdrant API key"
    )
    
    # Security
    jwt_secret_key: str = Field(
        default="dev-jwt-secret",
        env=("JWT_SECRET_KEY", "JWT_SECRET", "jwt_secret"),
        description="JWT secret key for authentication"
    )
    api_key: str = Field(
        default="dev-api-key",
        env=("API_KEY", "BACKEND_API_KEY", "backend_api_key"),
        description="API key for authentication"
    )
    
    # Logging
    log_level: str = Field(
        default="INFO",
        env="LOG_LEVEL",
        description="Logging level"
    )
    backend_log_level: Optional[str] = Field(
        default=None,
        env="BACKEND_LOG_LEVEL",
        description="Backend-specific logging level (overrides LOG_LEVEL)"
    )
    log_forwarding_enabled: bool = Field(
        default=False,
        env="LOG_FORWARDING_ENABLED",
        description="Enable log forwarding"
    )
    log_forwarding_endpoint: Optional[str] = Field(
        default=None,
        env="LOG_FORWARDING_ENDPOINT",
        description="Log forwarding endpoint URL"
    )
    log_include_stacktrace: bool = Field(
        default=False,
        env="LOG_INCLUDE_STACKTRACE",
        description="Include stack traces in logs"
    )

    # Communication Logging
    enable_communication_logging: bool = Field(
        default=True,
        env="ENABLE_COMMUNICATION_LOGGING",
        description="Enable detailed communication logging between services"
    )
    log_websocket_payloads: bool = Field(
        default=True,
        env="LOG_WEBSOCKET_PAYLOADS",
        description="Log WebSocket message payloads"
    )
    max_log_payload_size: int = Field(
        default=10240,  # 10KB
        env="MAX_LOG_PAYLOAD_SIZE",
        description="Maximum size of payloads to log (bytes)"
    )
    communication_sensitive_fields: List[str] = Field(
        default=["password", "token", "api_key", "secret", "private_key"],
        env="COMMUNICATION_SENSITIVE_FIELDS",
        description="Fields to sanitize in communication logs"
    )

    # WebSocket wire format (frontend + broadcast)
    ws_schema_version: int = Field(
        default=1,
        ge=1,
        env="WS_SCHEMA_VERSION",
        description="Integer version stamped on outbound WebSocket messages to the dashboard",
    )
    ws_market_broadcast_min_interval_ms: int = Field(
        default=0,
        ge=0,
        env="WS_MARKET_BROADCAST_MIN_INTERVAL_MS",
        description="Minimum milliseconds between market data_update broadcasts per symbol (0=disabled)",
    )
    ws_broadcast_metrics_interval: int = Field(
        default=0,
        ge=0,
        env="WS_BROADCAST_METRICS_INTERVAL",
        description="Emit a ws_broadcast_volume log every N broadcasts (0=disabled)",
    )
    
    # Backend Configuration
    backend_host: str = Field(
        default="0.0.0.0",
        env="BACKEND_HOST",
        description="Backend host address"
    )
    backend_port: int = Field(
        default=8000,
        env="BACKEND_PORT",
        description="Backend port number"
    )
    backend_reload: bool = Field(
        default=False,
        env="BACKEND_RELOAD",
        description="Enable auto-reload in development"
    )
    auto_create_db_schema: bool = Field(
        default=True,
        env="AUTO_CREATE_DB_SCHEMA",
        description="Automatically create database tables/enums on startup if missing"
    )
    
    # Trading Configuration
    initial_balance: float = Field(
        default=20000.0,
        env="INITIAL_BALANCE",
        description="Initial balance for paper trading (in INR)"
    )
    paper_trading_mode: bool = Field(
        default=True,
        env="PAPER_TRADING_MODE",
        description="When True, paper trading (no real orders); when False, live trading. Also set by TRADING_MODE=paper|live."
    )
    reset_paper_state_on_startup: bool = Field(
        default=True,
        env="RESET_PAPER_STATE_ON_STARTUP",
        description=(
            "When True in paper mode, backend clears positions/trades on startup. "
            "Set False to preserve paper portfolio across restarts."
        ),
    )
    agent_status_timeout_grace_seconds: int = Field(
        default=30,
        env="AGENT_STATUS_TIMEOUT_GRACE_SECONDS",
        description=(
            "Grace window to reuse last successful agent status after timeout, "
            "avoiding transient DEGRADED flicker."
        ),
    )
    agent_status_command_timeout_seconds: float = Field(
        default=15.0,
        env="AGENT_STATUS_COMMAND_TIMEOUT_SECONDS",
        ge=1.0,
        description=(
            "Timeout for backend -> agent get_status command. "
            "Raised from 5s to reduce false timeouts during CPU spikes."
        ),
    )

    @model_validator(mode="after")
    def sync_paper_trading_with_trading_mode(self):
        """Align paper_trading_mode with TRADING_MODE env if set."""
        trading_mode = os.environ.get("TRADING_MODE", "").strip().lower()
        if trading_mode == "paper":
            object.__setattr__(self, "paper_trading_mode", True)
        elif trading_mode == "live":
            object.__setattr__(self, "paper_trading_mode", False)
        return self

    contract_value_btc: float = Field(
        default=0.001,
        env="CONTRACT_VALUE_BTC",
        description="BTC notional per contract lot (must match agent paper model)",
    )
    isolated_margin_leverage: int = Field(
        default=5,
        env="ISOLATED_MARGIN_LEVERAGE",
        description="Leverage for isolated margin display (must match agent)",
    )

    # Risk Management Settings (must match agent config)
    stop_loss_percentage: float = Field(
        default=0.01,
        env="STOP_LOSS_PERCENTAGE",
        description="Stop loss percentage (default: 1%)"
    )
    take_profit_percentage: float = Field(
        default=0.015,
        env="TAKE_PROFIT_PERCENTAGE",
        description="Take profit percentage (default: 1.5%)"
    )
    enforce_ema200_trend_filter: bool = Field(
        default=True,
        env="ENFORCE_EMA200_TREND_FILTER",
        description="Require trend alignment with EMA200 in backtest analysis"
    )
    
    # CORS
    cors_origins: Union[str, List[str]] = Field(
        default="http://localhost:3000,http://localhost:3001",
        env="CORS_ORIGINS",
        description="Allowed CORS origins (comma-separated)"
    )
    
    @field_validator("cors_origins", mode="after")
    @classmethod
    def parse_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """Parse comma-separated CORS origins string."""
        try:
            if isinstance(v, list):
                return [str(origin).strip() for origin in v if str(origin).strip()]
            if isinstance(v, str):
                # Remove any newlines, carriage returns, and extra whitespace
                v = v.replace('\n', '').replace('\r', '').replace('\t', ' ').strip()
                if not v:
                    return ["http://localhost:3000", "http://localhost:3001"]
                # Split by comma and clean each origin
                origins = [origin.strip() for origin in v.split(",") if origin.strip()]
                if not origins:
                    return ["http://localhost:3000", "http://localhost:3001"]
                return origins
            # Fallback
            return ["http://localhost:3000", "http://localhost:3001"]
        except Exception as e:
            # If parsing fails, return default
            # Note: Logger may not be initialized at config load time, so use print for warnings
            import sys
            import structlog
            try:
                logger = structlog.get_logger()
                logger.warning(
                    "cors_origins_parse_failed",
                    service="backend",
                    error=str(e),
                    value=repr(v),
                    fallback=["http://localhost:3000", "http://localhost:3001"]
                )
            except Exception:
                # Fallback to print if logger not available
                print(f"Warning: Failed to parse CORS_ORIGINS: {e}, value: {repr(v)}", file=sys.stderr)
            return ["http://localhost:3000", "http://localhost:3001"]
    
    # Telegram Alerts (Optional)
    telegram_bot_token: Optional[str] = Field(
        default=None,
        env=("TELEGRAM_BOT_TOKEN", "telegram_bot_token"),
        description="Telegram bot token for alert notifications"
    )
    telegram_chat_id: Optional[str] = Field(
        default=None,
        env=("TELEGRAM_CHAT_ID", "telegram_chat_id"),
        description="Telegram chat ID for alert notifications"
    )
    
    @field_validator("telegram_bot_token", "telegram_chat_id", mode="before")
    @classmethod
    def empty_string_to_none(cls, v: Optional[str]) -> Optional[str]:
        """Normalize empty strings to None for optional settings."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("jwt_secret_key", "api_key", mode="before")
    @classmethod
    def normalize_security_defaults(cls, v: Optional[str]):
        """Treat blank strings as missing so defaults apply."""
        if isinstance(v, str) and not v.strip():
            return None
        return v
    
    # Rate Limiting
    rate_limit_requests: int = Field(
        default=100,
        env="RATE_LIMIT_REQUESTS",
        description="Rate limit requests per window"
    )
    rate_limit_window: int = Field(
        default=60,
        env="RATE_LIMIT_WINDOW",
        description="Rate limit window in seconds"
    )

    app_environment: str = Field(
        default="development",
        env=("ENVIRONMENT", "APP_ENV"),
        description="Deployment environment name (e.g. development, production)",
    )
    strict_secrets: bool = Field(
        default=False,
        env="STRICT_SECRETS",
        description="When True (or ENVIRONMENT=production), reject placeholder secrets",
    )
    cors_internal_origins: Optional[str] = Field(
        default=None,
        env="CORS_INTERNAL_ORIGINS",
        description="Comma-separated extra CORS origins (e.g. Docker internal http://frontend:3000)",
    )

    def get_cors_allow_origins(self) -> List[str]:
        """Merge CORS_ORIGINS with optional CORS_INTERNAL_ORIGINS."""
        merged = list(self.cors_origins)
        raw = self.cors_internal_origins
        if not raw or not str(raw).strip():
            return merged
        extra = (
            str(raw)
            .replace("\n", "")
            .replace("\r", "")
            .replace("\t", " ")
            .strip()
        )
        for origin in (o.strip() for o in extra.split(",") if o.strip()):
            if origin not in merged:
                merged.append(origin)
        return merged

    @model_validator(mode="after")
    def validate_no_placeholder_secrets(self) -> Settings:
        """Reject trivial placeholder secrets when STRICT_SECRETS or production."""
        env_name = (
            os.environ.get("ENVIRONMENT", "").strip().lower()
            or self.app_environment.strip().lower()
        )
        must_validate = self.strict_secrets or env_name == "production"
        if not must_validate:
            return self

        def bad(v: str) -> bool:
            s = (v or "").strip()
            if not s:
                return True
            low = s.lower()
            if low in {"changeme", "xxx", "placeholder", "dev-api-key", "dev-jwt-secret"}:
                return True
            if low.startswith("dev-"):
                return True
            return False

        if bad(self.jwt_secret_key):
            raise ValueError(
                "JWT_SECRET_KEY is missing or looks like a development placeholder. "
                "Set a strong secret, or use ENVIRONMENT=development with STRICT_SECRETS=false."
            )
        if bad(self.api_key):
            raise ValueError(
                "API_KEY is missing or looks like a development placeholder. "
                "Set a strong API key, or use ENVIRONMENT=development with STRICT_SECRETS=false."
            )
        if bad(self.delta_exchange_api_key):
            raise ValueError(
                "DELTA_EXCHANGE_API_KEY is missing or looks like a placeholder. "
                "Set real exchange credentials, or use ENVIRONMENT=development with STRICT_SECRETS=false."
            )
        if bad(self.delta_exchange_api_secret):
            raise ValueError(
                "DELTA_EXCHANGE_API_SECRET is missing or looks like a placeholder. "
                "Set real exchange credentials, or use ENVIRONMENT=development with STRICT_SECRETS=false."
            )
        return self


try:
    settings = Settings()
except Exception as e:
    # Configuration errors must be printed to stderr since logger may not be initialized
    # This is acceptable for startup errors that prevent the application from starting
    import sys
    
    # Check if either env file exists to provide more specific guidance.
    env_exists = ROOT_ENV_PATH.exists() or ROOT_ENV_EXAMPLE_PATH.exists()
    
    # Try to extract which field failed from Pydantic error
    error_str = str(e)
    missing_field = None
    if "field required" in error_str.lower():
        # Try to extract field name from error message
        import re
        match = re.search(r"['\"]([^'\"]+)['\"]", error_str)
        if match:
            missing_field = match.group(1)
    
    error_msg = f"""
{'='*70}
ERROR: Failed to load backend configuration
{'='*70}

Error: {error_str}
"""
    
    if env_exists:
        error_msg += f"""
Env files in use (later overrides earlier):
  - defaults : {ROOT_ENV_EXAMPLE_PATH} ({'present' if ROOT_ENV_EXAMPLE_PATH.exists() else 'MISSING'})
  - secrets  : {ROOT_ENV_PATH} ({'present' if ROOT_ENV_PATH.exists() else 'MISSING'})

However, there are issues with the configuration:
"""
        if missing_field:
            error_msg += f"  - Missing or invalid: {missing_field}\n"
        else:
            error_msg += "  - One or more required variables are missing or invalid\n"

        error_msg += """
Required secrets (must be in root .env):
  - DATABASE_URL (PostgreSQL connection URL with password)
  - DELTA_EXCHANGE_API_KEY / DELTA_EXCHANGE_API_SECRET (Delta credentials)
  - JWT_SECRET_KEY (>= 32 chars random)
  - API_KEY (>= 32 chars random)

Non-secret defaults live in .env.example (ports, CORS, rate limits, flags, ...).

To fix:
  1. Ensure root .env contains all secrets above (no empty values).
  2. Ensure .env.example exists in the project root for non-secret defaults.
  3. Verify variable formats are correct.
  4. See docs/13-debugging.md and docs/10-deployment.md for detailed help.
"""
    else:
        error_msg += f"""
No env files found in the project root:
  - {ROOT_ENV_EXAMPLE_PATH}
  - {ROOT_ENV_PATH}

Required secrets (place in root .env):
  - DATABASE_URL, DELTA_EXCHANGE_API_KEY, DELTA_EXCHANGE_API_SECRET, JWT_SECRET_KEY, API_KEY

Non-secret defaults (place in committed .env.example):
  - ports, CORS, rate limits, feature flags, thresholds.

To fix:
  1. Keep .env.example committed for non-secret defaults.
  2. Create root .env with secrets only.
  3. Or export required variables in the process environment.
  4. See docs/11-build-guide.md for setup instructions.
"""
    
    error_msg += f"""
Additional checks:
  - Ensure PostgreSQL is running and accessible
  - Ensure Redis is running (if required)
  - Verify DATABASE_URL connection string format is correct
{'='*70}
"""
    print(error_msg, file=sys.stderr)
    sys.exit(1)
