'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { Portfolio } from '@/types'
import { cn } from '@/lib/utils'
import { LoadingSpinner, LoadingSkeleton } from './LoadingSpinner'

interface PortfolioSummaryProps {
  portfolio?: Portfolio
  isLoading?: boolean
}

export function PortfolioSummary({ portfolio, isLoading = false }: PortfolioSummaryProps) {
  if (isLoading || !portfolio) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Portfolio Value</CardTitle>
        </CardHeader>
        <CardContent>
          <LoadingSkeleton className="py-4" />
        </CardContent>
      </Card>
    )
  }

  const parseNumber = (value: number | string | undefined): number => {
    if (value === undefined || value === null) return 0
    return typeof value === 'string' ? parseFloat(value) || 0 : value
  }

  const formatCurrency = (value: number | string | undefined) => {
    const numValue = parseNumber(value)
    return `$${numValue.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`
  }

  const totalUnrealizedPnL = parseNumber(portfolio.total_unrealized_pnl)
  const totalRealizedPnL = parseNumber(portfolio.total_realized_pnl)
  const totalPnL = totalUnrealizedPnL + totalRealizedPnL
  const totalValue = parseNumber(portfolio.total_value)
  const initialValue = totalValue - totalPnL
  const pnlPercentage = initialValue > 0 ? (totalPnL / initialValue) * 100 : 0
  const isPositive = totalPnL >= 0
  const availableBalance = parseNumber(portfolio.available_balance)

  return (
    <Card role="region" aria-label="Portfolio Summary">
      <CardHeader>
        <CardTitle>Portfolio Value</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-baseline justify-between">
          <div>
            <div className="text-3xl font-bold">{formatCurrency(totalValue)}</div>
            <div className="flex items-center gap-2 mt-1">
              <Badge
                variant={isPositive ? 'default' : 'destructive'}
                className={cn(
                  'flex items-center gap-1',
                  isPositive && 'bg-success text-white hover:bg-success/90',
                  !isPositive && 'bg-error text-white hover:bg-error/90'
                )}
              >
                {isPositive ? (
                  <TrendingUp className="h-3 w-3" />
                ) : (
                  <TrendingDown className="h-3 w-3" />
                )}
                {isPositive ? '+' : ''}
                {pnlPercentage.toFixed(2)}%
              </Badge>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-4 pt-4 border-t">
          <div>
            <div className="text-sm text-muted-foreground mb-1">Cash</div>
            <div className="text-xl font-semibold">
              {formatCurrency(availableBalance)}
            </div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground mb-1">Positions</div>
            <div className="text-xl font-semibold">
              {formatCurrency(totalValue - availableBalance)}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {portfolio.open_positions || 0} open
            </div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground mb-1">PnL</div>
            <div
              className={cn(
                'text-xl font-semibold',
                isPositive ? 'text-success' : 'text-error'
              )}
            >
              {isPositive ? '+' : ''}
              {formatCurrency(totalPnL)}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {totalUnrealizedPnL !== 0 &&
                `Unrealized: ${formatCurrency(totalUnrealizedPnL)}`}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

