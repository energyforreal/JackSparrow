#!/usr/bin/env python3
"""
Idempotent migration: model_registry, model_deployments, prediction_audit,
and model_performance.model_registry_id.

Run from project root. Uses DATABASE_URL from .env (sync URL; script uses sync engine).
"""

import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from sqlalchemy import create_engine, text

def get_sync_url(url: str) -> str:
    """Ensure sync driver (psycopg2) for migration script."""
    if not url:
        return url
    if "asyncpg" in url:
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        return url
    return url


def run():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)
    sync_url = get_sync_url(database_url)
    engine = create_engine(sync_url)
    print("Running model governance migration...")

    with engine.connect() as conn:
        # 1. model_registry
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS model_registry (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                version VARCHAR(64) NOT NULL,
                checksum VARCHAR(128),
                artifact_path VARCHAR(512),
                status VARCHAR(32) NOT NULL DEFAULT 'registered',
                metadata JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(name, version)
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_model_registry_name ON model_registry(name);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_model_registry_status ON model_registry(status);"))
        conn.commit()
        print("  model_registry: OK")

        # 2. model_deployments
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS model_deployments (
                id SERIAL PRIMARY KEY,
                model_registry_id INTEGER NOT NULL,
                deployed_at TIMESTAMPTZ NOT NULL,
                environment VARCHAR(64),
                status VARCHAR(32) NOT NULL DEFAULT 'active',
                metadata JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_model_deployments_registry ON model_deployments(model_registry_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_model_deployments_deployed_at ON model_deployments(deployed_at);"))
        conn.commit()
        print("  model_deployments: OK")

        # 3. prediction_audit
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS prediction_audit (
                id SERIAL PRIMARY KEY,
                request_id VARCHAR(255) NOT NULL,
                model_version VARCHAR(64),
                symbol VARCHAR(50) NOT NULL,
                confidence DECIMAL(5, 4),
                latency_ms DECIMAL(12, 2),
                source VARCHAR(32),
                outcome_reference VARCHAR(255),
                metadata JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prediction_audit_request_id ON prediction_audit(request_id);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prediction_audit_symbol_created ON prediction_audit(symbol, created_at);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_prediction_audit_source ON prediction_audit(source);"))
        conn.commit()
        print("  prediction_audit: OK")

        # 4. model_performance.model_registry_id (add column if missing)
        r = conn.execute(text("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'model_performance' AND column_name = 'model_registry_id';
        """))
        if r.scalar() is None:
            conn.execute(text("ALTER TABLE model_performance ADD COLUMN model_registry_id INTEGER;"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_model_performance_registry_id ON model_performance(model_registry_id);"))
            conn.commit()
            print("  model_performance.model_registry_id: added")
        else:
            print("  model_performance.model_registry_id: already present")

    print("Migration completed.")


if __name__ == "__main__":
    run()
