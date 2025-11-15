"""
Configuration management for agent service.

Handles environment variable loading, validation, and default values.
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Agent settings loaded from environment variables."""
    
    # Database
    database_url: str = Field(
        ...,
        env="DATABASE_URL",
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
        env="DELTA_EXCHANGE_API_KEY",
        description="Delta Exchange API key"
    )
    delta_exchange_api_secret: str = Field(
        ...,
        env="DELTA_EXCHANGE_API_SECRET",
        description="Delta Exchange API secret"
    )
    delta_exchange_base_url: str = Field(
        default="https://api.delta.exchange",
        env="DELTA_EXCHANGE_BASE_URL",
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
    
    # Feature Server
    feature_server_port: int = Field(
        default=8001,
        env="FEATURE_SERVER_PORT",
        description="Feature server port"
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
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()

