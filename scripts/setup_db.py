#!/usr/bin/env python3
"""
Database setup script for JackSparrow Trading Agent.

This script initializes the PostgreSQL database with TimescaleDB extension
and creates all necessary tables for the trading agent system.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv

# Load environment variables from project root
load_dotenv(dotenv_path=project_root / ".env")


def setup_database():
    """Initialize database with TimescaleDB and create tables."""
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not found in environment variables")
        print("Please set DATABASE_URL in the project root .env file")
        sys.exit(1)
    
    print(f"Connecting to database...")
    
    try:
        # Create engine
        engine = create_engine(database_url, echo=False)
        
        with engine.connect() as conn:
            # Enable TimescaleDB extension (optional)
            print("Enabling TimescaleDB extension...")
            timescaledb_available = False
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
                conn.commit()
                print("✓ TimescaleDB extension enabled")
                timescaledb_available = True
            except Exception as e:
                if "timescaledb" in str(e).lower() and "not available" in str(e).lower():
                    # Rollback the failed transaction
                    conn.rollback()
                    print("⚠ TimescaleDB extension is not installed")
                    print("  Tables will be created as regular PostgreSQL tables (not hypertables)")
                    print("  To install TimescaleDB, see: https://docs.timescale.com/install/latest/self-hosted/")
                    timescaledb_available = False
                else:
                    conn.rollback()
                    raise
            
            # Create ENUM types for enum columns
            print("Creating ENUM types...")
            enums = [
                ("tradeside", ["BUY", "SELL"]),
                ("tradestatus", ["PENDING", "EXECUTED", "FAILED", "CANCELLED"]),
                ("ordertype", ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]),
                ("positionstatus", ["OPEN", "CLOSED", "LIQUIDATED"]),
                ("signaltype", ["BUY", "SELL", "HOLD", "STRONG_BUY", "STRONG_SELL"]),
            ]
            
            for enum_name, values in enums:
                values_str = ", ".join(f"'{v}'" for v in values)
                try:
                    conn.execute(text(f"CREATE TYPE IF NOT EXISTS {enum_name} AS ENUM ({values_str});"))
                    conn.commit()
                    print(f"  ✓ Created ENUM type '{enum_name}'")
                except Exception as e:
                    conn.rollback()
                    # If enum already exists, that's okay
                    if "already exists" in str(e).lower():
                        print(f"  ⚠ ENUM type '{enum_name}' already exists, skipping")
                    else:
                        print(f"  ✗ Failed to create ENUM type '{enum_name}': {e}")
                        raise
            
            # Create trades table (hypertable)
            print("Creating trades table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS trades (
                    id SERIAL PRIMARY KEY,
                    trade_id VARCHAR(255) UNIQUE NOT NULL,
                    symbol VARCHAR(50) NOT NULL,
                    side tradeside NOT NULL,
                    quantity DECIMAL(18, 8) NOT NULL,
                    price DECIMAL(18, 8) NOT NULL,
                    order_type ordertype NOT NULL,
                    status tradestatus NOT NULL,
                    executed_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    reasoning_chain_id VARCHAR(255),
                    model_predictions JSONB,
                    metadata JSONB
                );
            """))
            conn.commit()
            
            # Convert trades to hypertable (if TimescaleDB available)
            if timescaledb_available:
                conn.execute(text("""
                    SELECT create_hypertable('trades', 'executed_at', 
                        if_not_exists => TRUE);
                """))
                conn.commit()
                print("✓ Trades table created as hypertable")
            else:
                print("✓ Trades table created (regular table)")
            
            # Create positions table
            print("Creating positions table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS positions (
                    id SERIAL PRIMARY KEY,
                    position_id VARCHAR(255) UNIQUE NOT NULL,
                    symbol VARCHAR(50) NOT NULL,
                    side tradeside NOT NULL,
                    quantity DECIMAL(18, 8) NOT NULL,
                    entry_price DECIMAL(18, 8) NOT NULL,
                    current_price DECIMAL(18, 8),
                    unrealized_pnl DECIMAL(18, 8),
                    opened_at TIMESTAMPTZ NOT NULL,
                    closed_at TIMESTAMPTZ,
                    status positionstatus NOT NULL DEFAULT 'OPEN'::positionstatus,
                    stop_loss DECIMAL(18, 8),
                    take_profit DECIMAL(18, 8),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
            """))
            conn.commit()
            print("✓ Positions table created")
            
            # Create decisions table
            print("Creating decisions table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id SERIAL PRIMARY KEY,
                    decision_id VARCHAR(255) UNIQUE NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    symbol VARCHAR(50) NOT NULL,
                    signal signaltype NOT NULL,
                    confidence DECIMAL(5, 4) NOT NULL,
                    position_size DECIMAL(5, 4),
                    reasoning_chain JSONB NOT NULL,
                    model_predictions JSONB,
                    market_context JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """))
            conn.commit()
            
            # Convert decisions to hypertable (if TimescaleDB available)
            if timescaledb_available:
                conn.execute(text("""
                    SELECT create_hypertable('decisions', 'timestamp', 
                        if_not_exists => TRUE);
                """))
                conn.commit()
                print("✓ Decisions table created as hypertable")
            else:
                print("✓ Decisions table created (regular table)")
            
            # Create performance_metrics table
            print("Creating performance_metrics table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id SERIAL PRIMARY KEY,
                    metric_id VARCHAR(255) UNIQUE NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    metric_type VARCHAR(50) NOT NULL,
                    metric_name VARCHAR(100) NOT NULL,
                    value DECIMAL(18, 8) NOT NULL,
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """))
            conn.commit()
            
            # Convert performance_metrics to hypertable (if TimescaleDB available)
            if timescaledb_available:
                conn.execute(text("""
                    SELECT create_hypertable('performance_metrics', 'timestamp', 
                        if_not_exists => TRUE);
                """))
                conn.commit()
                print("✓ Performance metrics table created as hypertable")
            else:
                print("✓ Performance metrics table created (regular table)")
            
            # Create model_performance table
            print("Creating model_performance table...")
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS model_performance (
                    id SERIAL PRIMARY KEY,
                    model_name VARCHAR(100) NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    prediction_accuracy DECIMAL(5, 4),
                    profit_contribution DECIMAL(18, 8),
                    weight DECIMAL(5, 4),
                    total_predictions INTEGER DEFAULT 0,
                    correct_predictions INTEGER DEFAULT 0,
                    metadata JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(model_name, timestamp)
                );
            """))
            conn.commit()
            
            # Convert model_performance to hypertable (if TimescaleDB available)
            if timescaledb_available:
                conn.execute(text("""
                    SELECT create_hypertable('model_performance', 'timestamp', 
                        if_not_exists => TRUE);
                """))
                conn.commit()
                print("✓ Model performance table created as hypertable")
            else:
                print("✓ Model performance table created (regular table)")
            
            # Create indexes
            print("Creating indexes...")
            conn.execute(text("""
                -- Trade indexes
                CREATE INDEX IF NOT EXISTS idx_trades_symbol_executed_at 
                    ON trades(symbol, executed_at DESC);
                CREATE INDEX IF NOT EXISTS idx_trade_executed_at_status 
                    ON trades(executed_at, status);
                CREATE INDEX IF NOT EXISTS idx_trade_status 
                    ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trade_symbol 
                    ON trades(symbol);
                
                -- Position indexes
                CREATE INDEX IF NOT EXISTS idx_positions_symbol_status 
                    ON positions(symbol, status);
                CREATE INDEX IF NOT EXISTS idx_position_status 
                    ON positions(status);
                CREATE INDEX IF NOT EXISTS idx_position_symbol 
                    ON positions(symbol);
                
                -- Decision indexes
                CREATE INDEX IF NOT EXISTS idx_decisions_symbol_timestamp 
                    ON decisions(symbol, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_decision_timestamp 
                    ON decisions(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_decision_symbol 
                    ON decisions(symbol);
                
                -- Performance metrics indexes
                CREATE INDEX IF NOT EXISTS idx_performance_metrics_type_timestamp 
                    ON performance_metrics(metric_type, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_performance_metrics_timestamp 
                    ON performance_metrics(timestamp DESC);
                
                -- Model performance indexes
                CREATE INDEX IF NOT EXISTS idx_model_performance_name_timestamp 
                    ON model_performance(model_name, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_model_performance_timestamp 
                    ON model_performance(timestamp DESC);
            """))
            conn.commit()
            print("✓ Indexes created")
            
        print("\n✓ Database setup completed successfully!")
        
    except OperationalError as e:
        print(f"\nERROR: Database connection failed: {e}")
        print("\nPlease ensure:")
        print("1. PostgreSQL is running")
        print("2. TimescaleDB extension is installed")
        print("3. DATABASE_URL is correct in the root .env file")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: Database setup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    setup_database()

