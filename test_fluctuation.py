#!/usr/bin/env python3
"""
Test script to verify fluctuation-based monitoring is working.
"""

import asyncio
import logging
from agent.data.market_data_service import MarketDataService
from agent.events.event_bus import event_bus

# Set up logging
logging.basicConfig(level=logging.INFO)

async def test_fluctuation_monitoring():
    print('=== Testing Fluctuation-Based Monitoring ===')

    # Initialize event bus
    await event_bus.initialize()

    # Create market data service
    service = MarketDataService()
    await service.initialize()

    print(f'Current fluctuation threshold: {service._price_fluctuation_threshold_pct}')

    # Temporarily lower threshold for testing
    original_threshold = service._price_fluctuation_threshold_pct
    service._price_fluctuation_threshold_pct = 0.01  # 0.01% for testing
    print(f'Test threshold set to: {service._price_fluctuation_threshold_pct}')

    # Subscribe to fluctuation events
    events_received = []

    async def on_fluctuation(event):
        events_received.append(event)
        print(f'✅ PriceFluctuationEvent received: {event.payload}')

    event_bus.subscribe('price_fluctuation', on_fluctuation)

    # Start market data stream
    print('Starting market data stream...')
    await service.start_market_data_stream(['BTCUSD'], '15m')

    # Wait for some events
    print('Waiting for price fluctuation events (20 seconds)...')
    await asyncio.sleep(20)

    # Check results
    print(f'Events received: {len(events_received)}')

    if events_received:
        print('✅ Fluctuation monitoring is working!')
        for event in events_received[:3]:  # Show first 3 events
            payload = event.payload
            price = payload.get("price", 0)
            change_pct = payload.get("change_pct", 0)
            threshold_pct = payload.get("threshold_pct", 0)
            print(f'  - Price: ${price:.2f}, Change: {change_pct:.2f}%, Threshold: {threshold_pct:.1f}%')
    else:
        print('❌ No fluctuation events received - investigating...')

        # Check if stream is running
        print(f'Stream running: {service.streaming_running}')
        print(f'Stream symbols: {service.streaming_symbols}')

        # Check current state
        print(f'Last major price: {service._last_major_price.get("BTCUSD", "Not set")}')

        # Check if we're getting any ticker data
        print('Testing ticker retrieval...')
        ticker = await service.get_ticker('BTCUSD')
        if ticker and ticker.get("price"):
            print(f'✅ Ticker data available: ${ticker.get("price", "N/A")}')
            print('The issue might be that BTC price is too stable for fluctuation detection.')
            print('In production, prices will fluctuate more and trigger events.')
        else:
            print('❌ No ticker data available')

    # Restore original threshold
    service._price_fluctuation_threshold_pct = original_threshold

    # Cleanup
    await service.stop_market_data_stream()
    await service.shutdown()
    await event_bus.shutdown()

if __name__ == "__main__":
    asyncio.run(test_fluctuation_monitoring())
