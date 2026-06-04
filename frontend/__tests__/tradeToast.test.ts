import { describe, expect, it } from '@jest/globals'

import {
  normalizeTradeRecord,
  shouldShowTradeExecutedToast,
} from '@/hooks/useTradingData'

describe('shouldShowTradeExecutedToast', () => {
  it('returns false for entry-only EXECUTED fills', () => {
    const payload = {
      trade_id: 'trade_abc',
      symbol: 'BTCUSD',
      side: 'BUY',
      quantity: 1,
      price: 71000,
      status: 'EXECUTED',
      executed_at: '2026-04-14T10:00:00Z',
    }
    expect(normalizeTradeRecord(payload)).toBeNull()
    expect(shouldShowTradeExecutedToast(payload)).toBe(false)
  })

  it('returns true for closed round-trip rows', () => {
    const payload = {
      trade_id: 'agent_pos_1',
      symbol: 'BTCUSD',
      side: 'SHORT',
      quantity: 1,
      entry_price: 70000,
      exit_price: 71000,
      status: 'CLOSED',
      record_kind: 'round_trip',
      executed_at: '2026-04-14T12:00:00Z',
      exit_time: '2026-04-14T12:00:00Z',
    }
    expect(shouldShowTradeExecutedToast(payload)).toBe(true)
  })
})
