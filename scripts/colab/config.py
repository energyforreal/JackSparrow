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

# Env-file split (matches agent/backend):
#   - .env.example (committed): non-secret defaults / thresholds.
#   - .env          (gitignored): secrets only.
def _get_project_root() -> Path:
    """Return repo root (directory containing both ``agent/`` and ``backend/``)."""
    try:
        start = Path(__file__).resolve().parent
        for candidate in (start, *start.parents):
            if (candidate / "agent").is_dir() and (candidate / "backend").is_dir():
                return candidate
    except (NameError, AttributeError):
        pass

    cwd = Path.cwd()
    if (cwd / "agent").is_dir() and (cwd / "backend").is_dir():
        return cwd
    current = cwd
    for _ in range(5):
        if (current / "agent").is_dir() and (current / "backend").is_dir():
            return current
        if current == current.parent:
            break
        current = current.parent
    return cwd


ROOT_PROJECT_ROOT = _get_project_root()
ROOT_ENV_PATH = ROOT_PROJECT_ROOT / ".env"
ROOT_ENV_EXAMPLE_PATH = ROOT_PROJECT_ROOT / ".env.example"


def _root_env_files() -> tuple[str, ...] | None:
    """Return existing env files in load order (.env.example, then .env)."""
    paths: list[str] = []
    if ROOT_ENV_EXAMPLE_PATH.exists():
        paths.append(str(ROOT_ENV_EXAMPLE_PATH))
    if ROOT_ENV_PATH.exists():
        paths.append(str(ROOT_ENV_PATH))
    return tuple(paths) if paths else None


class Settings(BaseSettings):
    """Agent settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=_root_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
        protected_namespaces=("settings_",),
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
    
    # Trading Session Defaults
    initial_balance: float = Field(
        default=10000.0,
        env="INITIAL_BALANCE",
        description="Initial trading balance"
    )
    trading_mode: str = Field(
        default="testnet",
        env="TRADING_MODE",
        description="Trading mode (testnet only for Colab upload parity)",
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
        description="Update interval in seconds"
    )
    timeframes: str = Field(
        default="15m,1h,4h",
        env="TIMEFRAMES",
        description="Comma-separated list of timeframes"
    )

    @field_validator("trading_mode", mode="before")
    @classmethod
    def normalize_trading_mode(cls, value: Optional[str]) -> str:
        """Normalize trading mode string."""
        if value is None:
            return "testnet"
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"paper", "live"}:
                return "testnet"
            if normalized != "testnet":
                raise ValueError("TRADING_MODE must be 'testnet'")
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
        raise ValueError("TIMEFRAMES must be a comma-separated string")

    @model_validator(mode="after")
    def enforce_testnet_runtime(self) -> "Settings":
        """Align Colab config with testnet-only runtime."""
        self.trading_mode = "testnet"
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
ERROR: Failed to load agent configuration
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
  - DATABASE_URL, DELTA_EXCHANGE_API_KEY, DELTA_EXCHANGE_API_SECRET

Non-secret defaults live in .env.example (MODEL_DIR, AGENT_SYMBOL, thresholds, ...).

To fix:
  1. Ensure root .env contains the required secrets above.
  2. Ensure .env.example is present in the project root for non-secret defaults.
  3. Verify variable formats are correct.
  4. See docs/13-debugging.md for detailed help.
"""
    else:
        error_msg += f"""
No env files found in the project root:
  - {ROOT_ENV_EXAMPLE_PATH}
  - {ROOT_ENV_PATH}

Required secrets (place in root .env):
  - DATABASE_URL, DELTA_EXCHANGE_API_KEY, DELTA_EXCHANGE_API_SECRET

Non-secret defaults (place in committed .env.example):
  - MODEL_PATH / MODEL_DIR / AGENT_SYMBOL / AGENT_INTERVAL / thresholds.

To fix:
  1. Keep .env.example committed for non-secret defaults.
  2. Create root .env with secrets only (or export them via the shell in Colab).
  3. Fill in all required values.
  4. See docs/11-build-guide.md for setup instructions.
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
