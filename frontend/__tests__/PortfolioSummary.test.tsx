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

const testnetPortfolio: Portfolio = {
  ...basePortfolio,
  total_value: 5909.61,
  total_value_usd: 69.52,
  available_balance: 5909.61,
  usd_inr_rate: 85,
  sync_status: 'live',
}

describe('PortfolioSummary', () => {
  it('shows USD as primary balance for delta_testnet', () => {
    render(<PortfolioSummary portfolio={testnetPortfolio} />)
    expect(screen.getByText(/\$69\.52/)).toBeInTheDocument()
    expect(screen.getByText('₹5,909.61')).toBeInTheDocument()
    expect(screen.getByText(/INR/)).toBeInTheDocument()
  })

  it('shows sync delayed badge when sync_status is stale', () => {
    render(<PortfolioSummary portfolio={basePortfolio} />)
    expect(screen.getByText('Sync delayed')).toBeInTheDocument()
    expect(screen.getByText('Testnet Account')).toBeInTheDocument()
  })
})
