import { render, screen } from '@testing-library/react'
import { PortfolioSummary } from '@/app/components/PortfolioSummary'
import type { Portfolio } from '@/types'

const basePortfolio: Portfolio = {
  total_value: 100000,
  available_balance: 50000,
  margin_used: 10000,
  open_positions: 1,
  total_unrealized_pnl: 500,
  total_realized_pnl: 200,
  data_source: 'delta_testnet',
  sync_status: 'stale',
}

describe('PortfolioSummary', () => {
  it('shows sync delayed badge when sync_status is stale', () => {
    render(<PortfolioSummary portfolio={basePortfolio} />)
    expect(screen.getByText('Sync delayed')).toBeInTheDocument()
    expect(screen.getByText('Testnet Account')).toBeInTheDocument()
  })
})
