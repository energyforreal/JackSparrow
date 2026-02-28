"""
Configuration management for agent service.

Handles environment variable loading, validation, and default values.
"""

import os
import sys
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, model_validator

# Determine ROOT_ENV_PATH with Colab compatibility
def _get_root_env_path() -> Path:
    """Get path to .env file, handling both Colab and local execution."""
    # Try using __file__ first (works in local execution)
    try:
        if __file__:
            config_path = Path(__file__).resolve()
            # agent/core/config.py -> project root (2 levels up)
            potential_root = config_path.parents[2]
            env_path = potential_root / ".env"
            if env_path.exists() or (potential_root / "agent").exists():
                return env_path
    except (NameError, AttributeError):
        # __file__ not available (e.g., in some Colab environments)
        pass
    
    # Fallback: search from current working directory
    cwd = Path.cwd()
    
    # Check if .env exists in current directory
    if (cwd / ".env").exists():
        return cwd / ".env"
    
    # Check if we're in project root
    if (cwd / "agent").exists():
        return cwd / ".env"
    
    # Search upward from current directory
    current = cwd
    for _ in range(5):  # Limit search depth
        if (current / "agent").exists():
            return current / ".env"
        if current == current.parent:
            break
        current = current.parent
    
    # Last resort: return a path that may not exist (will be handled by pydantic)
    return cwd / ".env"

ROOT_ENV_PATH = _get_root_env_path()


class Settings(BaseSettings):
    """Agent settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        # Make env_file optional - if it doesn't exist, use environment variables only
        env_file=str(ROOT_ENV_PATH) if ROOT_ENV_PATH.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
        protected_namespaces=("settings_",),
        # In Colab, environment variables are preferred over .env file
        env_ignore_empty=True,
    )
    
    # Database
    database_url: str = Field(
        ...,
        env=("DATABASE_URL", "database_url"),
        description="PostgreSQL database connection URL"
    )
    environment: str = Field(
        default="local",
        env=("ENVIRONMENT", "APP_ENV", "environment"),
        description="Deployment environment identifier (e.g., local, dev, prod)"
    )
    
    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379",
        env="REDIS_URL",
        description="Redis connection URL"
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
    
    # Model Configuration
    model_path: Optional[str] = Field(
        default=None,
        env="MODEL_PATH",
        description="Path to production model file"
    )
    model_dir: str = Field(
        default="./agent/model_storage",
        env="MODEL_DIR",
        description="Directory for model discovery"
    )
    model_discovery_enabled: bool = Field(
        default=True,
        env="MODEL_DISCOVERY_ENABLED",
        description="Enable automatic model discovery"
    )
    model_auto_register: bool = Field(
        default=True,
        env="MODEL_AUTO_REGISTER",
        description="Auto-register discovered models"
    )
    allow_feature_fallback_predictions: bool = Field(
        default=False,
        env="ALLOW_FEATURE_FALLBACK_PREDICTIONS",
        description=(
            "DEPRECATED: Previously allowed feature-based fallback predictions when no ML "
            "models were available. This setting is now ignored and feature-based fallbacks "
            "are disabled so that all trading decisions require real ML model predictions."
        ),
    )
    
    # Agent Configuration
    agent_start_mode: str = Field(
        default="MONITORING",
        env="AGENT_START_MODE",
        description="Agent start mode"
    )
    agent_symbol: str = Field(
        default="BTCUSD",
        env="AGENT_SYMBOL",
        description="Default trading symbol"
    )
    agent_interval: str = Field(
        default="15m",
        env="AGENT_INTERVAL",
        description="Default analysis interval"
    )
    
    # Trading Mode
    paper_trading_mode: bool = Field(
        default=True,
        env="PAPER_TRADING_MODE",
        description="Enable paper trading mode (default: True). Set to False for live trading."
    )
    
    # Risk Management
    max_position_size: float = Field(
        default=0.1,
        env="MAX_POSITION_SIZE",
        description="Maximum position size as fraction of portfolio"
    )
    max_portfolio_heat: float = Field(
        default=0.3,
        env="MAX_PORTFOLIO_HEAT",
        description="Maximum portfolio heat"
    )
    stop_loss_percentage: float = Field(
        default=0.02,
        env="STOP_LOSS_PERCENTAGE",
        description="Stop loss percentage"
    )
    take_profit_percentage: float = Field(
        default=0.05,
        env="TAKE_PROFIT_PERCENTAGE",
        description="Take profit percentage"
    )
    max_daily_loss: float = Field(
        default=0.05,
        env="MAX_DAILY_LOSS",
        description="Maximum daily loss as fraction of portfolio"
    )
    max_drawdown: float = Field(
        default=0.15,
        env="MAX_DRAWDOWN",
        description="Maximum drawdown as fraction of portfolio"
    )
    max_consecutive_losses: int = Field(
        default=5,
        env="MAX_CONSECUTIVE_LOSSES",
        description="Maximum consecutive losses before stopping"
    )
    min_time_between_trades: int = Field(
        default=300,
        env="MIN_TIME_BETWEEN_TRADES",
        description="Minimum time between trades in seconds"
    )
    
    # Logging
    log_level: str = Field(
        default="INFO",
        env="LOG_LEVEL",
        description="Logging level"
    )
    agent_log_level: Optional[str] = Field(
        default=None,
        env="AGENT_LOG_LEVEL",
        description="Agent-specific logging level (overrides LOG_LEVEL)"
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
    
    # Feature Server
    feature_server_port: int = Field(
        default=8001,
        env="FEATURE_SERVER_PORT",
        description="Feature server port"
    )
    feature_server_host: str = Field(
        default="0.0.0.0",
        env="FEATURE_SERVER_HOST",
        description="Feature server host address"
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
    
    # WebSocket Configuration
    agent_websocket_host: str = Field(
        default="0.0.0.0",
        env="AGENT_WS_HOST",
        description="Host for agent WebSocket server"
    )
    agent_websocket_port: int = Field(
        default=8002,
        env="AGENT_WS_PORT",
        description="Port for agent WebSocket server"
    )
    backend_websocket_url: str = Field(
        default="ws://localhost:8000/ws/agent",
        alias="BACKEND_WS_URL",
        description="Backend WebSocket URL for agent event client"
    )
    
    # Trading Session Defaults
    initial_balance: float = Field(
        default=10000.0,
        env="INITIAL_BALANCE",
        description="Initial trading balance"
    )
    trading_mode: str = Field(
        default="paper",
        env="TRADING_MODE",
        description="Trading mode (paper/live)"
    )
    trading_symbol: str = Field(
        default="BTCUSD",
        env="TRADING_SYMBOL",
        description="Trading symbol"
    )
    min_confidence_threshold: float = Field(
        default=0.65,
        env="MIN_CONFIDENCE_THRESHOLD",
        description="Minimum confidence threshold for trades"
    )
    update_interval: int = Field(
        default=900,
        env="UPDATE_INTERVAL",
        description="Update interval in seconds (legacy - used for candle-based operations)"
    )
    price_fluctuation_threshold_pct: float = Field(
        default=0.5,
        env="PRICE_FLUCTUATION_THRESHOLD_PCT",
        description="Percentage threshold for price fluctuations that trigger ML pipeline (e.g., 0.5 = 0.5%)"
    )
    fast_poll_interval: float = Field(
        default=0.5,
        env="FAST_POLL_INTERVAL",
        description="Fast polling interval in seconds for continuous ticker monitoring (controls API call frequency)"
    )
    timeframes: str = Field(
        default="15m,1h,4h",
        env="TIMEFRAMES",
        description="Comma-separated list of timeframes"
    )

    # WebSocket Configuration
    websocket_enabled: bool = Field(
        default=True,
        env="WEBSOCKET_ENABLED",
        description="Enable WebSocket streaming for real-time data (default: True)"
    )
    websocket_url: str = Field(
        default="wss://socket.india.delta.exchange",
        env="WEBSOCKET_URL",
        description="Delta Exchange WebSocket URL"
    )
    websocket_reconnect_attempts: int = Field(
        default=5,
        env="WEBSOCKET_RECONNECT_ATTEMPTS",
        description="Maximum WebSocket reconnection attempts"
    )
    websocket_reconnect_delay: float = Field(
        default=5.0,
        env="WEBSOCKET_RECONNECT_DELAY",
        description="Delay between WebSocket reconnection attempts in seconds"
    )
    websocket_heartbeat_interval: float = Field(
        default=30.0,
        env="WEBSOCKET_HEARTBEAT_INTERVAL",
        description="WebSocket heartbeat interval in seconds"
    )
    websocket_fallback_poll_interval: float = Field(
        default=60.0,
        env="WEBSOCKET_FALLBACK_POLL_INTERVAL",
        description="REST API polling interval when WebSocket is unavailable (seconds)"
    )

    @field_validator("trading_mode", mode="before")
    @classmethod
    def normalize_trading_mode(cls, value: Optional[str]) -> str:
        """Normalize trading mode string."""
        if value is None:
            return "paper"
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized not in {"paper", "live"}:
                raise ValueError("TRADING_MODE must be either 'paper' or 'live'")
            return normalized
        raise ValueError("TRADING_MODE must be a string")

    @field_validator("agent_start_mode", mode="before")
    @classmethod
    def validate_start_mode(cls, value: Optional[str]) -> str:
        """Ensure agent start mode is supported."""
        allowed = {"MONITORING", "PAUSED", "EMERGENCY_STOP"}
        mode = (value or "MONITORING").strip().upper()
        if mode not in allowed:
            raise ValueError(
                f"AGENT_START_MODE must be one of {', '.join(sorted(allowed))}"
            )
        return mode

    @field_validator("timeframes", mode="before")
    @classmethod
    def normalize_timeframes(cls, value: Optional[str]) -> str:
        """Normalize timeframe string by trimming whitespace and duplicates."""
        if not value:
            return "15m"
        if isinstance(value, str):
            cleaned = [tf.strip() for tf in value.split(",") if tf.strip()]
            return ",".join(dict.fromkeys(cleaned)) or "15m"

    @field_validator("price_fluctuation_threshold_pct", mode="before")
    @classmethod
    def validate_price_fluctuation_threshold(cls, value: Optional[float]) -> float:
        """Validate price fluctuation threshold is positive."""
        if value is None:
            return 0.5

        # Handle string inputs from environment variables
        if isinstance(value, str):
            try:
                threshold = float(value)
            except ValueError:
                raise ValueError("PRICE_FLUCTUATION_THRESHOLD_PCT must be a valid number")
        elif isinstance(value, (int, float)):
            threshold = float(value)
        else:
            raise ValueError("PRICE_FLUCTUATION_THRESHOLD_PCT must be a number")

        if threshold <= 0:
            raise ValueError("PRICE_FLUCTUATION_THRESHOLD_PCT must be positive")
        if threshold > 100:
            raise ValueError("PRICE_FLUCTUATION_THRESHOLD_PCT cannot exceed 100%")
        return threshold

    @field_validator("fast_poll_interval", mode="before")
    @classmethod
    def validate_fast_poll_interval(cls, value: Optional[float]) -> float:
        """Validate fast poll interval is reasonable."""
        if value is None:
            return 0.5

        # Handle string inputs from environment variables
        if isinstance(value, str):
            try:
                interval = float(value)
            except ValueError:
                raise ValueError("FAST_POLL_INTERVAL must be a valid number")
        elif isinstance(value, (int, float)):
            interval = float(value)
        else:
            raise ValueError("FAST_POLL_INTERVAL must be a number")

        if interval <= 0:
            raise ValueError("FAST_POLL_INTERVAL must be positive")
        if interval > 60:
            raise ValueError("FAST_POLL_INTERVAL cannot exceed 60 seconds (too slow for real-time)")
        return interval
        raise ValueError("TIMEFRAMES must be a comma-separated string")

    @model_validator(mode="after")
    def sync_trading_flags(self) -> "Settings":
        """Keep trading_mode and paper_trading_mode aligned."""
        trading_mode_env = os.getenv("TRADING_MODE")
        paper_mode_env = os.getenv("PAPER_TRADING_MODE")

        normalized_mode = (self.trading_mode or "paper").lower()
        derived_paper_flag = normalized_mode != "live"

        if trading_mode_env is not None:
            # TRADING_MODE takes precedence – update boolean flag accordingly
            if paper_mode_env and self.paper_trading_mode != derived_paper_flag:
                print(
                    "Warning: PAPER_TRADING_MODE overrides are ignored when TRADING_MODE is set. "
                    "Keeping values in sync.",
                    file=sys.stderr,
                )
            self.paper_trading_mode = derived_paper_flag
            self.trading_mode = normalized_mode
        elif paper_mode_env is not None:
            # Only PAPER_TRADING_MODE provided – update string representation
            self.trading_mode = "paper" if self.paper_trading_mode else "live"
        else:
            # Neither provided explicitly – derive bool from mode, defaulting to paper
            self.paper_trading_mode = derived_paper_flag
            self.trading_mode = normalized_mode

        return self

    def parsed_timeframes(self) -> List[str]:
        """Return normalized timeframes as list."""
        return [tf for tf in (self.timeframes or "").split(",") if tf]
    
try:
    settings = Settings()
except Exception as e:
    # Configuration errors must be printed to stderr since logger may not be initialized
    # This is acceptable for startup errors that prevent the application from starting
    import sys
    
    # Check if .env file exists to provide more specific guidance
    env_exists = ROOT_ENV_PATH.exists()
    
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
ERROR: Failed to load agent configuration
{'='*70}

Error: {error_str}
"""
    
    if env_exists:
        error_msg += f"""
The .env file exists at: {ROOT_ENV_PATH}

However, there are issues with the configuration:
"""
        if missing_field:
            error_msg += f"  - Missing or invalid: {missing_field}\n"
        else:
            error_msg += "  - One or more required variables are missing or invalid\n"
        
        error_msg += f"""
Required environment variables (check your .env file):
  - DATABASE_URL (PostgreSQL connection URL, e.g., postgresql://user:pass@localhost:5432/dbname)
  - DELTA_EXCHANGE_API_KEY (Delta Exchange API key from your account)
  - DELTA_EXCHANGE_API_SECRET (Delta Exchange API secret from your account)

Optional environment variables:
  - MODEL_PATH (Path to specific model file, e.g., models/xgboost_BTCUSD_15m.pkl)
  - MODEL_DIR (Directory for model discovery, default: ./agent/model_storage)
  - AGENT_SYMBOL (Trading symbol, default: BTCUSD)
  - AGENT_INTERVAL (Analysis interval, default: 15m)

To fix:
  1. Open the .env file: {ROOT_ENV_PATH}
  2. Ensure all required variables are set (no empty values)
  3. Verify variable formats are correct
  4. Run validation: python scripts/validate-env.py
  5. Ensure database is initialized: python scripts/setup_db.py
  6. See docs/troubleshooting-local-startup.md for detailed help
"""
    else:
        error_msg += f"""
The .env file was not found at: {ROOT_ENV_PATH}

Required environment variables:
  - DATABASE_URL (PostgreSQL connection URL)
  - DELTA_EXCHANGE_API_KEY (Delta Exchange API key)
  - DELTA_EXCHANGE_API_SECRET (Delta Exchange API secret)

Optional environment variables:
  - MODEL_PATH (Path to specific model file)
  - MODEL_DIR (Directory for model discovery, default: ./agent/model_storage)
  - AGENT_SYMBOL (Trading symbol, default: BTCUSD)
  - AGENT_INTERVAL (Analysis interval, default: 15m)

To fix:
  1. Copy .env.example to .env in the project root (if .env.example exists)
  2. Or create .env file manually with all required variables
  3. Fill in all required values
  4. Run validation: python scripts/validate-env.py
  5. Initialize database: python scripts/setup_db.py
  6. See docs/11-build-guide.md for setup instructions
"""
    
    error_msg += f"""
Additional checks:
  - Ensure PostgreSQL is running and accessible
  - Ensure Redis is running (if required)
  - Verify DATABASE_URL connection string format is correct
  - Run database setup: python scripts/setup_db.py
{'='*70}
"""
    print(error_msg, file=sys.stderr)
    sys.exit(1)
