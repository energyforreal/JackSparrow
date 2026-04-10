import asyncio
from backend.core.database import AsyncSessionLocal
from backend.core.database import Position, Trade
from sqlalchemy import delete

async def clean_database():
    async with AsyncSessionLocal() as db:
        try:
            # Delete all positions
            await db.execute(delete(Position))
            # Delete all trades
            await db.execute(delete(Trade))
            await db.commit()
            print("Database cleaned: All positions and trades deleted")
        except Exception as e:
            await db.rollback()
            print(f"Error cleaning database: {e}")

asyncio.run(clean_database())
