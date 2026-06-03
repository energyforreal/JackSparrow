import {
  RECENT_TRADES_MAX,
  TERMINAL_TRADE_STATUSES,
  normalizeTradeRecord,
} from '@/hooks/useTradingData'

describe('useTradingData', () => {
  it('exports recent trades cap aligned with REST bootstrap', () => {
    expect(RECENT_TRADES_MAX).toBe(50)
  })

  it('accepts common terminal trade statuses', () => {
    expect(TERMINAL_TRADE_STATUSES.has('CLOSED')).toBe(true)
    expect(TERMINAL_TRADE_STATUSES.has('FILLED')).toBe(true)
    expect(TERMINAL_TRADE_STATUSES.has('EXECUTED')).toBe(true)
    expect(TERMINAL_TRADE_STATUSES.has('COMPLETED')).toBe(true)
    expect(TERMINAL_TRADE_STATUSES.has('OPEN')).toBe(false)
  })

  it('normalizeTradeRecord drops EXECUTED entry fills', () => {
    expect(
      normalizeTradeRecord({
        trade_id: 'trade_x',
        status: 'EXECUTED',
        executed_at: '2026-01-01T00:00:00Z',
      })
    ).toBeNull()
  })
})
