"""
Database connection and SQLAlchemy models.

Provides database session management and ORM models.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
from sqlalchemy import create_engine, Column, Integer, String, DECIMAL, DateTime, JSON, Enum as SQLEnum, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMPTZ
from sqlalchemy.engine import Engine
import enum
from typing import Generator

from backend.core.config import settings

# Create base class for models
Base = declarative_base()

# Create engine (async-compatible)
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=False,
    future=True
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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
    side = Column(SQLEnum(TradeSide), nullable=False)
    quantity = Column(DECIMAL(18, 8), nullable=False)
    price = Column(DECIMAL(18, 8), nullable=False)
    order_type = Column(SQLEnum(OrderType), nullable=False)
    status = Column(SQLEnum(TradeStatus), nullable=False, default=TradeStatus.PENDING)
    executed_at = Column(TIMESTAMPTZ, nullable=False, index=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    reasoning_chain_id = Column(String(255), nullable=True)
    model_predictions = Column(JSONB, nullable=True)
    metadata = Column(JSONB, nullable=True)


class Position(Base):
    """Position model."""
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    position_id = Column(String(255), unique=True, nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(SQLEnum(TradeSide), nullable=False)
    quantity = Column(DECIMAL(18, 8), nullable=False)
    entry_price = Column(DECIMAL(18, 8), nullable=False)
    current_price = Column(DECIMAL(18, 8), nullable=True)
    unrealized_pnl = Column(DECIMAL(18, 8), nullable=True, default=Decimal("0"))
    opened_at = Column(TIMESTAMPTZ, nullable=False)
    closed_at = Column(TIMESTAMPTZ, nullable=True)
    status = Column(SQLEnum(PositionStatus), nullable=False, default=PositionStatus.OPEN)
    stop_loss = Column(DECIMAL(18, 8), nullable=True)
    take_profit = Column(DECIMAL(18, 8), nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)
    updated_at = Column(TIMESTAMPTZ, default=datetime.utcnow, onupdate=datetime.utcnow)


class Decision(Base):
    """Decision model."""
    __tablename__ = "decisions"
    
    id = Column(Integer, primary_key=True, index=True)
    decision_id = Column(String(255), unique=True, nullable=False, index=True)
    timestamp = Column(TIMESTAMPTZ, nullable=False, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    signal = Column(SQLEnum(SignalType), nullable=False)
    confidence = Column(DECIMAL(5, 4), nullable=False)
    position_size = Column(DECIMAL(5, 4), nullable=True)
    reasoning_chain = Column(JSONB, nullable=False)
    model_predictions = Column(JSONB, nullable=True)
    market_context = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)


class PerformanceMetric(Base):
    """Performance metric model."""
    __tablename__ = "performance_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    metric_id = Column(String(255), unique=True, nullable=False, index=True)
    timestamp = Column(TIMESTAMPTZ, nullable=False, index=True)
    metric_type = Column(String(50), nullable=False, index=True)
    metric_name = Column(String(100), nullable=False)
    value = Column(DECIMAL(18, 8), nullable=False)
    metadata = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)


class ModelPerformance(Base):
    """Model performance tracking model."""
    __tablename__ = "model_performance"
    
    id = Column(Integer, primary_key=True, index=True)
    model_name = Column(String(100), nullable=False, index=True)
    timestamp = Column(TIMESTAMPTZ, nullable=False, index=True)
    prediction_accuracy = Column(DECIMAL(5, 4), nullable=True)
    profit_contribution = Column(DECIMAL(18, 8), nullable=True)
    weight = Column(DECIMAL(5, 4), nullable=True)
    total_predictions = Column(Integer, default=0)
    correct_predictions = Column(Integer, default=0)
    metadata = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMPTZ, default=datetime.utcnow)


# Database dependency for FastAPI
def get_db() -> Generator[Session, None, None]:
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

