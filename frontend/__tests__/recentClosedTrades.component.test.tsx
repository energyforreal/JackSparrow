import { render, screen } from '@testing-library/react'
import { describe, expect, it } from '@jest/globals'

import { RecentTrades } from '@/app/components/RecentTrades'
import type { Trade } from '@/types'

describe('RecentTrades closed-only table', () => {
  it('renders closed-trade analytics columns and values', () => {
    const trades: Trade[] = [
      {
        trade_id: 'closed_pos_1',
        position_id: 'pos_1',
        symbol: 'BTCUSD',
        side: 'BUY',
        quantity: 12,
        price: 52000,
        entry_price: 50000,
        exit_price: 52000,
        pnl: 1660,
        status: 'CLOSED',
        entry_time: '2026-04-14T10:00:00Z',
        exit_time: '2026-04-14T10:10:30Z',
        duration_seconds: 630,
        executed_at: '2026-04-14T10:10:30Z',
      },
    ]

    render(<RecentTrades trades={trades} usdInrRate={83} />)

    expect(screen.getByText('Entry Time')).toBeInTheDocument()
    expect(screen.getByText('Exit Time')).toBeInTheDocument()
    expect(screen.getByText('Duration')).toBeInTheDocument()
    expect(screen.getByText('Entry Price')).toBeInTheDocument()
    expect(screen.getByText('Exit Price')).toBeInTheDocument()
    expect(screen.getByText('PnL')).toBeInTheDocument()
    expect(screen.getByText('10m 30s')).toBeInTheDocument()
    expect(screen.getByText('CLOSED')).toBeInTheDocument()
    expect(screen.getByText('BTCUSD')).toBeInTheDocument()
  })
})
