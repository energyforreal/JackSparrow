"""
Database connection and SQLAlchemy models.

Provides database session management and ORM models.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, AsyncGenerator
from sqlalchemy import (
    Column,
    Integer,
    String,
    DECIMAL,
    DateTime,
    JSON,
    Enum as SQLEnum,
    text,
    TIMESTAMP,
    Index,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSONB, ENUM as PostgresEnum
import enum

from backend.core.config import settings

# Create base class for models
Base = declarative_base()

# PostgreSQL-compatible timestamp with timezone
TIMESTAMPTZ = TIMESTAMP(timezone=True)

# Convert database URL to async format if needed
def get_async_database_url(database_url: str) -> str:
    """Convert database URL to async format.
    
    Args:
        database_url: Original database URL
        
    Returns:
        Async-compatible database URL
    """
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql+psycopg2://"):
        return database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql+asyncpg://"):
        return database_url
    else:
        # Assume it's postgresql:// and convert
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Create async engine
async_database_url = get_async_database_url(settings.database_url)
engine = create_async_engine(
    async_database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,  # Recycle connections after 1 hour
    echo=False,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# Enums
class TradeSide(str, enum.Enum):
    """Trade side enumeration."""
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, enum.Enum):
    """Trade status enumeration."""
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class OrderType(str, enum.Enum):
    """Order type enumeration."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class PositionStatus(str, enum.Enum):
    """Position status enumeration."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    LIQUIDATED = "LIQUIDATED"


class SignalType(str, enum.Enum):
    """Signal type enumeration."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    STRONG_BUY = "STRONG_BUY"
    STRONG_SELL = "STRONG_SELL"


# Models
class Trade(Base):
    """Trade model."""
    __tablename__ = "trades"
    
    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(String(255), unique=True, nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(PostgresEnum(TradeSide, name='tradeside', create_type=False), nullable=False)
    quantity = Column(DECIMAL(18, 8), nullable=False)
    price = Column(DECIMAL(18, 8), nullable=False)
    order_type = Column(PostgresEnum(OrderType, name='ordertype', create_type=False), nullable=False)
    status = Column(PostgresEnum(TradeStatus, name='tradestatus', create_type=False), nullable=False, default=TradeStatus.PENDING)
    executed_at = Column(TIMESTAMPTZ, nullable=False, index=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    reasoning_chain_id = Column(String(255), nullable=True)
    model_predictions = Column(JSONB, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    
    # Composite index for common query pattern: symbol + executed_at
    __table_args__ = (
        Index('idx_trade_symbol_executed_at', 'symbol', 'executed_at'),
    )


class Position(Base):
    """Position model."""
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    position_id = Column(String(255), unique=True, nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(PostgresEnum(TradeSide, name='tradeside', create_type=False), nullable=False)
    quantity = Column(DECIMAL(18, 8), nullable=False)
    entry_price = Column(DECIMAL(18, 8), nullable=False)
    current_price = Column(DECIMAL(18, 8), nullable=True)
    unrealized_pnl = Column(DECIMAL(18, 8), nullable=True, default=Decimal("0"))
    opened_at = Column(TIMESTAMPTZ, nullable=False)
    closed_at = Column(TIMESTAMPTZ, nullable=True)
    status = Column(PostgresEnum(PositionStatus, name='positionstatus', create_type=False), nullable=False, default=PositionStatus.OPEN)
    stop_loss = Column(DECIMAL(18, 8), nullable=True)
    take_profit = Column(DECIMAL(18, 8), nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    updated_at = Column(TIMESTAMPTZ, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Composite index for common query pattern: symbol + status
    __table_args__ = (
        Index('idx_position_symbol_status', 'symbol', 'status'),
    )


class Decision(Base):
    """Decision model."""
    __tablename__ = "decisions"
    
    id = Column(Integer, primary_key=True, index=True)
    decision_id = Column(String(255), unique=True, nullable=False, index=True)
    timestamp = Column(TIMESTAMPTZ, nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    signal = Column(PostgresEnum(SignalType, name='signaltype', create_type=False), nullable=False)
    confidence = Column(DECIMAL(5, 4), nullable=False)
    position_size = Column(DECIMAL(5, 4), nullable=True)
    reasoning_chain = Column(JSONB, nullable=False)
    model_predictions = Column(JSONB, nullable=True)
    market_context = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    
    # Composite index for common query pattern: symbol + timestamp
    __table_args__ = (
        Index('idx_decision_symbol_timestamp', 'symbol', 'timestamp'),
    )


class PerformanceMetric(Base):
    """Performance metric model."""
    __tablename__ = "performance_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    metric_id = Column(String(255), unique=True, nullable=False, index=True)
    timestamp = Column(TIMESTAMPTZ, nullable=False, index=True)
    metric_type = Column(String(50), nullable=False, index=True)
    metric_name = Column(String(100), nullable=False)
    value = Column(DECIMAL(18, 8), nullable=False)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)


class ModelPerformance(Base):
    """Model performance tracking model."""
    __tablename__ = "model_performance"
    
    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String(100), nullable=False, index=True)
    model_registry_id = Column(Integer, nullable=True, index=True)  # FK to model_registry.id when set
    timestamp = Column(TIMESTAMPTZ, nullable=False, index=True)
    prediction_accuracy = Column(DECIMAL(5, 4), nullable=True)
    profit_contribution = Column(DECIMAL(18, 8), nullable=True)
    weight = Column(DECIMAL(5, 4), nullable=True)
    total_predictions = Column(Integer, default=0)
    correct_predictions = Column(Integer, default=0)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)


class ModelRegistry(Base):
    """Model registry: name, version, checksum, artifact path, status."""
    __tablename__ = "model_registry"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    version = Column(String(64), nullable=False, index=True)
    checksum = Column(String(128), nullable=True)
    artifact_path = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False, default="registered", index=True)  # registered, active, deprecated
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    updated_at = Column(TIMESTAMPTZ, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_model_registry_name_version", "name", "version", unique=True),
    )


class ModelDeployment(Base):
    """Active deployment history for models."""
    __tablename__ = "model_deployments"
    
    id = Column(Integer, primary_key=True, index=True)
    model_registry_id = Column(Integer, nullable=False, index=True)  # FK to model_registry.id
    deployed_at = Column(TIMESTAMPTZ, nullable=False, index=True)
    environment = Column(String(64), nullable=True)  # dev, staging, production
    status = Column(String(32), nullable=False, default="active", index=True)  # active, superseded
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)


class TradeOutcomeRecord(Base):
    """Closed position outcomes for adaptive learning and performance analytics."""

    __tablename__ = "trade_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    position_id = Column(String(255), nullable=True, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(String(16), nullable=True)
    signal = Column(String(64), nullable=True)
    entry_price = Column(DECIMAL(24, 8), nullable=False)
    exit_price = Column(DECIMAL(24, 8), nullable=False)
    quantity = Column(DECIMAL(24, 8), nullable=False)
    pnl = Column(DECIMAL(24, 8), nullable=True)
    pnl_pct = Column(DECIMAL(12, 6), nullable=True)
    close_reason = Column(String(64), nullable=True)
    opened_at = Column(TIMESTAMPTZ, nullable=True)
    closed_at = Column(TIMESTAMPTZ, nullable=False, default=datetime.utcnow)
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_trade_outcomes_symbol_closed", "symbol", "closed_at"),
    )


class PredictionAudit(Base):
    """Audit log for prediction requests: request_id, model version, confidence, latency, outcome reference."""
    __tablename__ = "prediction_audit"
    
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(255), nullable=False, index=True)
    model_version = Column(String(64), nullable=True, index=True)  # or ensemble descriptor
    symbol = Column(String(50), nullable=False, index=True)
    confidence = Column(DECIMAL(5, 4), nullable=True)
    latency_ms = Column(DECIMAL(12, 2), nullable=True)
    source = Column(String(32), nullable=True, index=True)  # model_service, agent
    outcome_reference = Column(String(255), nullable=True)  # e.g. decision_id or trade_id for later linkage
    metadata_json = Column("metadata", JSONB, nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_prediction_audit_symbol_created", "symbol", "created_at"),
    )


# Database dependency for FastAPI
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session.
    
    Yields:
        AsyncSession: Database session
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

