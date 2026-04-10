"""
Test script to verify portfolio budget constraints and calculations.
"""
import asyncio
from backend.core.database import AsyncSessionLocal
from backend.services.portfolio_service import PortfolioService
from backend.services.trade_persistence_service import TradePersistenceService
from backend.core.config import settings
import uuid

async def test_budget_constraints():
    """Test that trades are properly constrained by budget."""
    print("=" * 60)
    print("PORTFOLIO BUDGET CONSTRAINT TEST")
    print("=" * 60)
    
    async with AsyncSessionLocal() as db:
        portfolio_service = PortfolioService()
        trade_service = TradePersistenceService()
        
        # Get initial portfolio state
        print("\n1. Initial Portfolio State:")
        summary = await portfolio_service.get_portfolio_summary(db)
        if summary:
            print(f"   Total Value: Rs {summary['total_value']:.2f}")
            print(f"   Available Balance: Rs {summary['available_balance']:.2f}")
            print(f"   Open Positions: {summary['open_positions']}")
            initial_balance = summary['available_balance']
        else:
            print("   Failed to get portfolio")
            return
        
        # Test 1: Try to create a trade within budget
        print("\n2. Test Trade #1: BTC at $95,000 (quantity = 0.1)")
        symbol = "BTCUSD"
        quantity = 0.1
        fill_price = 95000.0
        trade_value = quantity * fill_price
        print(f"   Trade value: ${trade_value:.2f} USD")
        
        try:
            trade_id_1 = str(uuid.uuid4())
            result = await trade_service.create_trade_and_position(
                trade_id=trade_id_1,
                symbol=symbol,
                side="BUY",
                quantity=quantity,
                fill_price=fill_price,
                stop_loss=fill_price * 0.98,
                take_profit=fill_price * 1.05
            )
            print(f"   ✓ Trade created: {result}")
            
            # Check portfolio after trade
            await portfolio_service.invalidate_portfolio_cache()
            summary = await portfolio_service.get_portfolio_summary(db)
            if summary:
                print(f"\n   Portfolio after trade:")
                print(f"   - Total Value: Rs {summary['total_value']:.2f}")
                print(f"   - Available Balance: Rs {summary['available_balance']:.2f}")
                print(f"   - Margin Used: Rs {summary['margin_used']:.2f}")
                print(f"   - Open Positions: {summary['open_positions']}")
                print(f"   - Unrealized PnL: Rs {summary['total_unrealized_pnl']:.2f}")
        except ValueError as e:
            print(f"   ✗ Trade rejected: {e}")
        
        # Test 2: Try to create another trade that would exceed budget
        print("\n3. Test Trade #2: ETH at $3,500 (quantity = 2.0, total $7,000)")
        quantity_2 = 2.0
        fill_price_2 = 3500.0
        trade_value_2 = quantity_2 * fill_price_2
        print(f"   Trade value: ${trade_value_2:.2f} USD")
        print(f"   Total would be: ${trade_value + trade_value_2:.2f} USD")
        
        try:
            trade_id_2 = str(uuid.uuid4())
            result = await trade_service.create_trade_and_position(
                trade_id=trade_id_2,
                symbol="ETHUSD",
                side="BUY",
                quantity=quantity_2,
                fill_price=fill_price_2,
                stop_loss=fill_price_2 * 0.98,
                take_profit=fill_price_2 * 1.05
            )
            print(f"   ✓ Trade created: {result}")
            
            # Check portfolio
            await portfolio_service.invalidate_portfolio_cache()
            summary = await portfolio_service.get_portfolio_summary(db)
            if summary:
                print(f"\n   Portfolio after 2nd trade:")
                print(f"   - Total Value: Rs {summary['total_value']:.2f}")
                print(f"   - Available Balance: Rs {summary['available_balance']:.2f}")
                print(f"   - Margin Used: Rs {summary['margin_used']:.2f}")
                print(f"   - Open Positions: {summary['open_positions']}")
        except ValueError as e:
            print(f"   ✗ Trade rejected (expected): {e}")
        
        # Test 3: Verify final portfolio state
        print("\n4. Final Portfolio State:")
        await portfolio_service.invalidate_portfolio_cache()
        summary = await portfolio_service.get_portfolio_summary(db)
        if summary:
            print(f"   Total Value: Rs {summary['total_value']:.2f}")
            print(f"   Available Balance: Rs {summary['available_balance']:.2f}")
            print(f"   Margin Used: Rs {summary['margin_used']:.2f}")
            print(f"   Total Unrealized PnL: Rs {summary['total_unrealized_pnl']:.2f}")
            print(f"   Total Realized PnL: Rs {summary['total_realized_pnl']:.2f}")
            print(f"   Open Positions: {summary['open_positions']}")
            
            if summary['open_positions'] > 0:
                print(f"\n   Open positions:")
                for pos in summary['positions']:
                    print(f"   - {pos['symbol']}: {pos['quantity']} @ ${pos['entry_price_usd']:.2f}")
                    print(f"     Unrealized PnL: Rs {pos['unrealized_pnl_inr']:.2f}")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_budget_constraints())
