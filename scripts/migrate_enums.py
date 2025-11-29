#!/usr/bin/env python3
"""
Database migration script to convert VARCHAR enum columns to PostgreSQL ENUM types.

This script migrates existing VARCHAR columns to proper PostgreSQL ENUM types
to fix the schema mismatch between the database and SQLAlchemy models.

WARNING: This script modifies your database schema. Always backup your database
before running migrations in production.

Usage:
    python scripts/migrate_enums.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from dotenv import load_dotenv

# Load environment variables from project root
load_dotenv(dotenv_path=project_root / ".env")


def check_enum_exists(conn, enum_name: str) -> bool:
    """Check if an ENUM type already exists in the database."""
    result = conn.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = :enum_name
        );
    """), {"enum_name": enum_name})
    return result.scalar()


def create_enum_types(conn):
    """Create PostgreSQL ENUM types if they don't exist."""
    enums = [
        ("tradeside", ["BUY", "SELL"]),
        ("tradestatus", ["PENDING", "EXECUTED", "FAILED", "CANCELLED"]),
        ("ordertype", ["MARKET", "LIMIT", "STOP", "STOP_LIMIT"]),
        ("positionstatus", ["OPEN", "CLOSED", "LIQUIDATED"]),
        ("signaltype", ["BUY", "SELL", "HOLD", "STRONG_BUY", "STRONG_SELL"]),
    ]
    
    for enum_name, values in enums:
        if check_enum_exists(conn, enum_name):
            print(f"  ⚠ ENUM type '{enum_name}' already exists, skipping creation")
            continue
        
        values_str = ", ".join(f"'{v}'" for v in values)
        try:
            conn.execute(text(f"CREATE TYPE {enum_name} AS ENUM ({values_str});"))
            conn.commit()
            print(f"  ✓ Created ENUM type '{enum_name}'")
        except Exception as e:
            conn.rollback()
            print(f"  ✗ Failed to create ENUM type '{enum_name}': {e}")
            raise


def check_column_type(conn, table_name: str, column_name: str) -> str:
    """Check the current data type of a column."""
    result = conn.execute(text("""
        SELECT data_type 
        FROM information_schema.columns 
        WHERE table_name = :table_name 
          AND column_name = :column_name;
    """), {"table_name": table_name, "column_name": column_name})
    
    row = result.fetchone()
    return row[0] if row else None


def migrate_column(conn, table_name: str, column_name: str, enum_type: str):
    """Migrate a VARCHAR column to an ENUM type."""
    current_type = check_column_type(conn, table_name, column_name)
    
    if not current_type:
        print(f"  ⚠ Column '{table_name}.{column_name}' not found, skipping")
        return False
    
    if current_type == "USER-DEFINED":
        # Check if it's already the correct enum
        result = conn.execute(text("""
            SELECT udt_name 
            FROM information_schema.columns 
            WHERE table_name = :table_name 
              AND column_name = :column_name;
        """), {"table_name": table_name, "column_name": column_name})
        udt_name = result.scalar()
        if udt_name == enum_type:
            print(f"  ✓ Column '{table_name}.{column_name}' already uses '{enum_type}'")
            return True
    
    if current_type not in ["character varying", "varchar"]:
        print(f"  ⚠ Column '{table_name}.{column_name}' is not VARCHAR (type: {current_type}), skipping")
        return False
    
    try:
        # Convert column to ENUM type
        # Using USING clause to cast existing VARCHAR values to ENUM
        conn.execute(text(f"""
            ALTER TABLE {table_name} 
            ALTER COLUMN {column_name} TYPE {enum_type} 
            USING {column_name}::{enum_type};
        """))
        conn.commit()
        print(f"  ✓ Migrated '{table_name}.{column_name}' to '{enum_type}'")
        return True
    except Exception as e:
        conn.rollback()
        print(f"  ✗ Failed to migrate '{table_name}.{column_name}': {e}")
        raise


def migrate_database():
    """Main migration function."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not found in environment variables")
        print("Please set DATABASE_URL in the project root .env file")
        sys.exit(1)
    
    print("=" * 60)
    print("Database ENUM Migration Script")
    print("=" * 60)
    print("\n⚠ WARNING: This script will modify your database schema.")
    print("   Always backup your database before running migrations.\n")
    
    response = input("Do you want to continue? (yes/no): ").strip().lower()
    if response not in ["yes", "y"]:
        print("Migration cancelled.")
        sys.exit(0)
    
    print(f"\nConnecting to database...")
    
    try:
        # Create engine
        engine = create_engine(database_url, echo=False)
        
        with engine.connect() as conn:
            # Start transaction
            trans = conn.begin()
            
            try:
                # Step 1: Create ENUM types
                print("\nStep 1: Creating ENUM types...")
                create_enum_types(conn)
                
                # Step 2: Migrate columns
                print("\nStep 2: Migrating columns to ENUM types...")
                
                migrations = [
                    ("trades", "side", "tradeside"),
                    ("trades", "order_type", "ordertype"),
                    ("trades", "status", "tradestatus"),
                    ("positions", "side", "tradeside"),
                    ("positions", "status", "positionstatus"),  # CRITICAL - fixes the error
                    ("decisions", "signal", "signaltype"),
                ]
                
                for table_name, column_name, enum_type in migrations:
                    migrate_column(conn, table_name, column_name, enum_type)
                
                # Commit transaction
                trans.commit()
                
                print("\n" + "=" * 60)
                print("✓ Migration completed successfully!")
                print("=" * 60)
                print("\nNext steps:")
                print("1. Restart your backend service")
                print("2. Verify that portfolio queries work correctly")
                print("3. Check backend logs for any remaining errors")
                
            except Exception as e:
                trans.rollback()
                print(f"\n✗ Migration failed: {e}")
                print("Transaction rolled back. Database state unchanged.")
                import traceback
                traceback.print_exc()
                sys.exit(1)
        
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
    migrate_database()

