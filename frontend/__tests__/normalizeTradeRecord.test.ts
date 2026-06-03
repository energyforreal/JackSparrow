import { describe, expect, it } from '@jest/globals'

import { normalizeTradeRecord } from '@/hooks/useTradingData'

describe('normalizeTradeRecord', () => {
  it('rejects entry-only EXECUTED order fills', () => {
    const row = normalizeTradeRecord({
      trade_id: 'trade_abc_123',
      symbol: 'BTCUSD',
      side: 'SELL',
      quantity: 1,
      price: 71000,
      status: 'EXECUTED',
      executed_at: '2026-04-14T10:00:00Z',
    })
    expect(row).toBeNull()
  })

  it('accepts CLOSED agent round-trip from position_close payload', () => {
    const row = normalizeTradeRecord({
      trade_id: 'agent_pos_91dbe9d2-032',
      position_id: 'pos_91dbe9d2-032',
      symbol: 'BTCUSD',
      side: 'SHORT',
      quantity: 1,
      entry_price: 71305.86947496,
      exit_price: 72650.63190143312,
      pnl: -123.56,
      pnl_usd: -1.4887189278495205,
      status: 'CLOSED',
      record_kind: 'round_trip',
      data_source: 'agent',
      entry_time: '2026-04-12T11:54:03.425188+00:00',
      exit_time: '2026-04-13T18:45:41.606563+00:00',
      duration_seconds: 10783.901188,
      exit_reason: 'signal_reversal',
      executed_at: '2026-04-13T18:45:41.606563+00:00',
    })

    expect(row).not.toBeNull()
    expect(row?.status).toBe('CLOSED')
    expect(row?.record_kind).toBe('round_trip')
    expect(row?.pnl).toBe(-123.56)
    expect(row?.duration_seconds).toBeCloseTo(10783.901188, 3)
    expect(row?.exit_reason).toBe('signal_reversal')
  })

  it('accepts exchange fill rows', () => {
    const row = normalizeTradeRecord({
      trade_id: 'fill_112233',
      symbol: 'BTCUSD',
      side: 'BUY',
      quantity: 5,
      price: 67200,
      status: 'FILLED',
      record_kind: 'fill',
      data_source: 'exchange_fill',
      executed_at: '2026-04-14T12:00:00Z',
    })
    expect(row).not.toBeNull()
    expect(row?.record_kind).toBe('fill')
    expect(row?.entry_time).toBeUndefined()
  })
})
