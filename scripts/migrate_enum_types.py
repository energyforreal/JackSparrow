#!/usr/bin/env python3
"""
Database migration script to convert VARCHAR status columns to PostgreSQL enum types.

This script fixes the schema mismatch between VARCHAR columns and enum type expectations.
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


def migrate_enum_types():
    """Migrate VARCHAR columns to PostgreSQL enum types."""
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not found in environment variables")
        print("Please set DATABASE_URL in the project root .env file")
        sys.exit(1)
    
    print("Connecting to database...")
    
    try:
        # Create engine
        engine = create_engine(database_url, echo=False)
        
        with engine.connect() as conn:
            # Start transaction
            trans = conn.begin()
            
            try:
                # Step 1: Create enum types if they don't exist
                print("\nStep 1: Creating ENUM types...")
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
                        # Check if enum type already exists
                        check_result = conn.execute(text(f"""
                            SELECT EXISTS (
                                SELECT 1 FROM pg_type WHERE typname = '{enum_name}'
                            );
                        """))
                        exists = check_result.fetchone()[0]
                        
                        if not exists:
                            conn.execute(text(f"CREATE TYPE {enum_name} AS ENUM ({values_str});"))
                            print(f"  ✓ Created ENUM type '{enum_name}'")
                        else:
                            print(f"  ✓ ENUM type '{enum_name}' already exists")
                    except Exception as e:
                        print(f"  ⚠ Error checking/creating ENUM type '{enum_name}': {e}")
                        raise
                
                conn.commit()
                trans = conn.begin()  # Start new transaction
                
                # Step 2: Check current column types
                print("\nStep 2: Checking current column types...")
                
                # Check positions.status
                result = conn.execute(text("""
                    SELECT data_type, udt_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'positions' AND column_name = 'status';
                """))
                pos_status_info = result.fetchone()
                
                # Check trades.status
                result = conn.execute(text("""
                    SELECT data_type, udt_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'trades' AND column_name = 'status';
                """))
                trade_status_info = result.fetchone()
                
                print(f"  positions.status: {pos_status_info[0] if pos_status_info else 'NOT FOUND'} ({pos_status_info[1] if pos_status_info else 'N/A'})")
                print(f"  trades.status: {trade_status_info[0] if trade_status_info else 'NOT FOUND'} ({trade_status_info[1] if trade_status_info else 'N/A'})")
                
                # Step 3: Migrate positions.status column
                if pos_status_info and pos_status_info[0] == 'character varying':
                    print("\nStep 3: Migrating positions.status from VARCHAR to positionstatus enum...")
                    
                    # Add temporary column with enum type
                    conn.execute(text("""
                        ALTER TABLE positions 
                        ADD COLUMN status_new positionstatus;
                    """))
                    
                    # Copy data with casting
                    conn.execute(text("""
                        UPDATE positions 
                        SET status_new = status::positionstatus;
                    """))
                    
                    # Drop old column
                    conn.execute(text("""
                        ALTER TABLE positions 
                        DROP COLUMN status;
                    """))
                    
                    # Rename new column
                    conn.execute(text("""
                        ALTER TABLE positions 
                        RENAME COLUMN status_new TO status;
                    """))
                    
                    # Set NOT NULL constraint
                    conn.execute(text("""
                        ALTER TABLE positions 
                        ALTER COLUMN status SET NOT NULL;
                    """))
                    
                    # Set default value
                    conn.execute(text("""
                        ALTER TABLE positions 
                        ALTER COLUMN status SET DEFAULT 'OPEN'::positionstatus;
                    """))
                    
                    print("  ✓ Migrated positions.status to enum type")
                else:
                    if pos_status_info and 'positionstatus' in pos_status_info[1]:
                        print("  ✓ positions.status already uses enum type")
                    else:
                        print("  ⚠ positions table or status column not found")
                
                # Step 4: Migrate trades.status column
                if trade_status_info and trade_status_info[0] == 'character varying':
                    print("\nStep 4: Migrating trades.status from VARCHAR to tradestatus enum...")
                    
                    # Add temporary column with enum type
                    conn.execute(text("""
                        ALTER TABLE trades 
                        ADD COLUMN status_new tradestatus;
                    """))
                    
                    # Copy data with casting
                    conn.execute(text("""
                        UPDATE trades 
                        SET status_new = status::tradestatus;
                    """))
                    
                    # Drop old column
                    conn.execute(text("""
                        ALTER TABLE trades 
                        DROP COLUMN status;
                    """))
                    
                    # Rename new column
                    conn.execute(text("""
                        ALTER TABLE trades 
                        RENAME COLUMN status_new TO status;
                    """))
                    
                    # Set NOT NULL constraint
                    conn.execute(text("""
                        ALTER TABLE trades 
                        ALTER COLUMN status SET NOT NULL;
                    """))
                    
                    # Set default value
                    conn.execute(text("""
                        ALTER TABLE trades 
                        ALTER COLUMN status SET DEFAULT 'PENDING'::tradestatus;
                    """))
                    
                    print("  ✓ Migrated trades.status to enum type")
                else:
                    if trade_status_info and 'tradestatus' in trade_status_info[1]:
                        print("  ✓ trades.status already uses enum type")
                    else:
                        print("  ⚠ trades table or status column not found")
                
                # Commit transaction
                conn.commit()
                
                print("\n✓ Migration completed successfully!")
                print("\nNote: You may need to restart the backend service for changes to take effect.")
                
            except Exception as e:
                trans.rollback()
                raise
        
    except OperationalError as e:
        print(f"\nERROR: Database connection failed: {e}")
        print("\nPlease ensure:")
        print("1. PostgreSQL is running")
        print("2. DATABASE_URL is correct in the root .env file")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate VARCHAR columns to PostgreSQL enum types")
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt"
    )
    args = parser.parse_args()
    
    print("=" * 60)
    print("Database Enum Type Migration")
    print("=" * 60)
    print("\nThis script will migrate VARCHAR status columns to PostgreSQL enum types.")
    print("This fixes the schema mismatch causing portfolio query errors.\n")
    
    if not args.yes:
        response = input("Do you want to continue? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Migration cancelled.")
            sys.exit(0)
    
    migrate_enum_types()

