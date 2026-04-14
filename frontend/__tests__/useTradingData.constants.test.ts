import { RECENT_TRADES_MAX } from '@/hooks/useTradingData'

describe('useTradingData', () => {
  it('exports recent trades cap aligned with REST bootstrap', () => {
    expect(RECENT_TRADES_MAX).toBe(50)
  })
})
