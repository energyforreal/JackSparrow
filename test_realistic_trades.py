"""
Test script with realistic trade sizes that fit within the ₹20,000 budget.
"""
import asyncio
from backend.core.database import AsyncSessionLocal
from backend.services.portfolio_service import PortfolioService
from backend.services.trade_persistence_service import TradePersistenceService
import uuid

async def test_realistic_trades():
    """Test trade execution with realistic sizes within budget."""
    print("=" * 70)
    print("REALISTIC PORTFOLIO TRADING TEST (Rs 20,000 Budget)")
    print("=" * 70)
    
    async with AsyncSessionLocal() as db:
        portfolio_service = PortfolioService()
        trade_service = TradePersistenceService()
        
        # Get initial portfolio state
        print("\n1. INITIAL PORTFOLIO STATE")
        print("-" * 70)
        summary = await portfolio_service.get_portfolio_summary(db)
        if summary:
            print(f"   Initial Balance: Rs {summary['available_balance']:.2f}")
            print(f"   In USD: ${summary['available_balance'] / summary['usd_inr_rate']:.2f}")
            print(f"   Open Positions: {summary['open_positions']}")
        
        # Calculate maximum trade sizes for different assets
        # Budget: ₹20,000 = ~$240 USD
        budget_usd = 20000 / 83
        print(f"\n   Total Budget in USD: ${budget_usd:.2f}")
        
        # Test Trade 1: Small BTC position (1 lot = 0.01 BTC)
        print("\n2. TEST TRADE #1: BTC (Small Position)")
        print("-" * 70)
        symbol_1 = "BTCUSD"
        quantity_1 = 0.001  # Tiny position
        fill_price_1 = 95000.0
        trade_value_1 = quantity_1 * fill_price_1
        print(f"   Asset: {symbol_1}")
        print(f"   Quantity: {quantity_1} BTC")
        print(f"   Entry Price: ${fill_price_1:.2f}")
        print(f"   Position Cost: ${trade_value_1:.2f} USD = Rs {trade_value_1 * 83:.2f}")
        print(f"   % of Budget: {(trade_value_1/budget_usd)*100:.1f}%")
        
        try:
            trade_id_1 = str(uuid.uuid4())
            result = await trade_service.create_trade_and_position(
                trade_id=trade_id_1,
                symbol=symbol_1,
                side="BUY",
                quantity=quantity_1,
                fill_price=fill_price_1,
                stop_loss=fill_price_1 * 0.98,
                take_profit=fill_price_1 * 1.05
            )
            print(f"   ✓ TRADE EXECUTED: Position ID = {result['position_id'][:8]}...")
            
            # Check portfolio after trade
            await portfolio_service.invalidate_portfolio_cache()
            summary = await portfolio_service.get_portfolio_summary(db)
            if summary:
                print(f"\n   Portfolio Update:")
                print(f"   • Total Value: Rs {summary['total_value']:.2f}")
                print(f"   • Available Balance: Rs {summary['available_balance']:.2f}")
                print(f"   • Margin Used: Rs {summary['margin_used']:.2f}")
                print(f"   • Open Positions: {summary['open_positions']}")
        except ValueError as e:
            print(f"   ✗ TRADE REJECTED: {e}")
        
        # Test Trade 2: Micro ETH position  
        print("\n3. TEST TRADE #2: ETH (Micro Position)")
        print("-" * 70)
        symbol_2 = "ETHUSD"
        quantity_2 = 0.01  # Tiny position
        fill_price_2 = 3500.0
        trade_value_2 = quantity_2 * fill_price_2
        print(f"   Asset: {symbol_2}")
        print(f"   Quantity: {quantity_2} ETH")
        print(f"   Entry Price: ${fill_price_2:.2f}")
        print(f"   Position Cost: ${trade_value_2:.2f} USD = Rs {trade_value_2 * 83:.2f}")
        print(f"   % of Budget: {(trade_value_2/budget_usd)*100:.1f}%")
        
        try:
            trade_id_2 = str(uuid.uuid4())
            result = await trade_service.create_trade_and_position(
                trade_id=trade_id_2,
                symbol=symbol_2,
                side="BUY",
                quantity=quantity_2,
                fill_price=fill_price_2,
                stop_loss=fill_price_2 * 0.98,
                take_profit=fill_price_2 * 1.05
            )
            print(f"   ✓ TRADE EXECUTED: Position ID = {result['position_id'][:8]}...")
            
            # Check portfolio
            await portfolio_service.invalidate_portfolio_cache()
            summary = await portfolio_service.get_portfolio_summary(db)
            if summary:
                print(f"\n   Portfolio Update:")
                print(f"   • Total Value: Rs {summary['total_value']:.2f}")
                print(f"   • Available Balance: Rs {summary['available_balance']:.2f}")
                print(f"   • Margin Used: Rs {summary['margin_used']:.2f}")
                print(f"   • Open Positions: {summary['open_positions']}")
        except ValueError as e:
            print(f"   ✗ TRADE REJECTED: {e}")
        
        # Test Trade 3: Try to exceed budget
        print("\n4. TEST TRADE #3: Exceeding Budget (Should Fail)")
        print("-" * 70)
        symbol_3 = "LTCUSD"
        quantity_3 = 5.0
        fill_price_3 = 500.0
        trade_value_3 = quantity_3 * fill_price_3
        print(f"   Asset: {symbol_3}")
        print(f"   Quantity: {quantity_3} LTC")
        print(f"   Entry Price: ${fill_price_3:.2f}")
        print(f"   Position Cost: ${trade_value_3:.2f} USD = Rs {trade_value_3 * 83:.2f}")
        print(f"   % of Budget: {(trade_value_3/budget_usd)*100:.1f}% (EXCEEDS 100%)")
        
        try:
            trade_id_3 = str(uuid.uuid4())
            result = await trade_service.create_trade_and_position(
                trade_id=trade_id_3,
                symbol=symbol_3,
                side="BUY",
                quantity=quantity_3,
                fill_price=fill_price_3
            )
            print(f"   ✗ UNEXPECTED: Trade executed when it should have failed!")
        except ValueError as e:
            print(f"   ✓ CORRECTLY REJECTED: {e}")
        
        # Final portfolio state
        print("\n5. FINAL PORTFOLIO STATE")
        print("-" * 70)
        await portfolio_service.invalidate_portfolio_cache()
        summary = await portfolio_service.get_portfolio_summary(db)
        if summary:
            print(f"   Total Portfolio Value: Rs {summary['total_value']:.2f}")
            print(f"   Available Cash: Rs {summary['available_balance']:.2f}")
            print(f"   Margin Used: Rs {summary['margin_used']:.2f}")
            print(f"   Total Unrealized PnL: Rs {summary['total_unrealized_pnl']:.2f}")
            print(f"   Open Positions: {summary['open_positions']}")
            
            if summary['open_positions'] > 0:
                print(f"\n   Open Positions:")
                for pos in summary['positions']:
                    pnl_pct = ((pos['current_price_usd'] - pos['entry_price_usd']) / pos['entry_price_usd'] * 100) if pos['entry_price_usd'] > 0 else 0
                    print(f"   • {pos['symbol']}: {pos['quantity']} @ ${pos['entry_price_usd']:.2f}")
                    print(f"     Unrealized PnL: Rs {pos['unrealized_pnl_inr']:.2f} ({pnl_pct:+.2f}%)")
    
    print("\n" + "=" * 70)
    print("✓ TEST COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_realistic_trades())
