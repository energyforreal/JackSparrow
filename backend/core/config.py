"""
Configuration management for backend service.

Handles environment variable loading, validation, and default values.
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
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
        ...,
        env="JWT_SECRET_KEY",
        description="JWT secret key for authentication"
    )
    api_key: str = Field(
        ...,
        env="API_KEY",
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
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:3001"],
        env="CORS_ORIGINS",
        description="Allowed CORS origins (comma-separated)"
    )
    
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
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()

