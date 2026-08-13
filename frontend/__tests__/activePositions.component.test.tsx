import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from '@jest/globals'

import { ActivePositions } from '@/app/components/ActivePositions'
import type { Position } from '@/types'

describe('ActivePositions table alignment', () => {
  const headers = [
    'Symbol',
    'Side',
    'Lev.',
    'Lots',
    'Entry',
    'Mark',
    'SL',
    'TP',
    'Liq.',
    'PnL',
    'Duration',
  ]

  it('renders eleven column headers and eleven cells per data row', () => {
    const positions: Position[] = [
      {
        position_id: 'ex_1',
        symbol: 'BTCUSD',
        side: 'SHORT',
        quantity: 1,
        lots: 1,
        entry_price_usd: 71000,
        current_price_usd: 70500,
        unrealized_pnl_inr: -415,
        liquidation_price_usd: 85000,
        stop_loss: 72000,
        take_profit: 69000,
        leverage: 10,
        opened_at: '2026-04-14T10:00:00Z',
        status: 'OPEN',
      },
    ]

    const { container } = render(<ActivePositions positions={positions} />)
    const table = container.querySelector('table')
    expect(table).not.toBeNull()

    const headerRow = table!.querySelector('thead tr')
    expect(headerRow).not.toBeNull()
    headers.forEach((label) => {
      expect(within(headerRow as HTMLElement).getByText(label)).toBeInTheDocument()
    })
    expect(headerRow!.querySelectorAll('th').length).toBe(11)

    const dataRow = table!.querySelector('tbody tr')
    expect(dataRow!.querySelectorAll('td').length).toBe(11)
    expect(screen.getByText('BTCUSD')).toBeInTheDocument()
    expect(screen.getByText('SHORT')).toBeInTheDocument()
  })

  it('loading skeleton uses eleven columns', () => {
    const { container } = render(<ActivePositions isLoading />)
    const headerRow = container.querySelector('thead tr')
    expect(headerRow!.querySelectorAll('th').length).toBe(11)
    const skeletonRow = container.querySelector('tbody tr')
    expect(skeletonRow!.querySelectorAll('td').length).toBe(11)
  })
})
