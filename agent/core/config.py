"""
Configuration management for agent service.

Handles environment variable loading, validation, and default values.
"""

from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Agent settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV_PATH),
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
        description="Update interval in seconds"
    )
    timeframes: str = Field(
        default="15m,1h,4h",
        env="TIMEFRAMES",
        description="Comma-separated list of timeframes"
    )
    
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
