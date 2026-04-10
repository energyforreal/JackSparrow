import asyncio
from backend.core.database import AsyncSessionLocal
from backend.services.portfolio_service import PortfolioService

async def test_portfolio():
    async with AsyncSessionLocal() as db:
        service = PortfolioService()
        summary = await service.get_portfolio_summary(db)
        
        if summary:
            print('Portfolio Summary:')
            print(f'  Total Value: Rs {summary["total_value"]:.2f}')
            print(f'  Available Balance: Rs {summary["available_balance"]:.2f}')
            print(f'  Margin Used: Rs {summary["margin_used"]:.2f}')
            print(f'  Open Positions: {summary["open_positions"]}')
            print(f'  Unrealized PnL: Rs {summary["total_unrealized_pnl"]:.2f}')
            print(f'  Realized PnL: Rs {summary["total_realized_pnl"]:.2f}')
            print(f'  USD/INR Rate: {summary["usd_inr_rate"]:.2f}')
        else:
            print('Failed to get portfolio summary')

asyncio.run(test_portfolio())
