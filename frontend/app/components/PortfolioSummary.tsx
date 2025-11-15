'use client'

interface PortfolioSummaryProps {
  portfolio?: {
    total_value?: number
    available_balance?: number
    open_positions?: number
    total_unrealized_pnl?: number
  }
}

export function PortfolioSummary({ portfolio }: PortfolioSummaryProps) {
  if (!portfolio) {
    return (
      <div className="bg-white rounded-lg shadow p-4">
        <h2 className="text-xl font-semibold mb-2">Portfolio</h2>
        <p className="text-gray-500">Loading...</p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h2 className="text-xl font-semibold mb-4">Portfolio Summary</h2>
      <div className="space-y-2">
        <div className="flex justify-between">
          <span className="text-gray-600">Total Value:</span>
          <span className="font-semibold">${portfolio.total_value?.toFixed(2) || '0.00'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">Available:</span>
          <span className="font-semibold">${portfolio.available_balance?.toFixed(2) || '0.00'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">Open Positions:</span>
          <span className="font-semibold">{portfolio.open_positions || 0}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">Unrealized P&L:</span>
          <span className={`font-semibold ${(portfolio.total_unrealized_pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600'}`}>
            ${portfolio.total_unrealized_pnl?.toFixed(2) || '0.00'}
          </span>
        </div>
      </div>
    </div>
  )
}

