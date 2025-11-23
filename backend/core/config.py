"""
Configuration management for backend service.

Handles environment variable loading, validation, and default values.
"""

from pathlib import Path
from typing import List, Optional, Union
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=str(ROOT_ENV_PATH),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
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
        default="https://api.delta.exchange",
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
    
    # Feature Server
    feature_server_url: str = Field(
        default="http://localhost:8001",
        env="FEATURE_SERVER_URL",
        description="MCP Feature Server URL"
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
    
try:
    settings = Settings()
except Exception as e:
    # Configuration errors must be printed to stderr since logger may not be initialized
    # This is acceptable for startup errors that prevent the application from starting
    import sys
    error_msg = f"""
{'='*70}
ERROR: Failed to load backend configuration
{'='*70}

Error: {str(e)}

Required environment variables:
  - DATABASE_URL (PostgreSQL connection URL)
  - DELTA_EXCHANGE_API_KEY (Delta Exchange API key)
  - DELTA_EXCHANGE_API_SECRET (Delta Exchange API secret)
  - JWT_SECRET_KEY (JWT secret key for authentication)
  - API_KEY (API key for authentication)

Please:
  1. Copy .env.example to .env in the project root
  2. Fill in all required values in the root .env file
  3. Ensure PostgreSQL and Redis are running
{'='*70}
"""
    print(error_msg, file=sys.stderr)
    sys.exit(1)
