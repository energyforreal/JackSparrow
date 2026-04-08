'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { Portfolio } from '@/types'
import { cn } from '@/lib/utils'
import { formatCurrency as formatInrCurrency } from '@/utils/formatters'

interface PortfolioSummaryProps {
  portfolio?: Portfolio
  isLoading?: boolean
}

export function PortfolioSummary({ portfolio, isLoading = false }: PortfolioSummaryProps) {
  if (isLoading) {
    return (
      <Card role="status" aria-label="Loading portfolio summary">
        <CardHeader>
          <CardTitle>Portfolio Value</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 animate-pulse">
          <div className="h-4 bg-muted rounded-md w-28" />
          <div className="h-10 bg-muted rounded-md w-48 max-w-[66%]" />
          <div className="h-6 bg-muted rounded-md w-24" />
          <div className="grid grid-cols-3 gap-4 pt-4 border-t">
            {[1, 2, 3].map((i) => (
              <div key={i} className="space-y-2">
                <div className="h-3 bg-muted rounded-md w-14" />
                <div className="h-7 bg-muted rounded-md w-24" />
                <div className="h-3 bg-muted rounded-md w-20" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!portfolio) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Portfolio Value</CardTitle>
        </CardHeader>
        <CardContent className="rounded-xl border border-dashed p-8 text-center">
          <p className="text-sm text-muted-foreground">No portfolio data yet</p>
          <p className="text-xs mt-2 text-muted-foreground/80">
            Connect to the agent and wait for the first portfolio snapshot over the WebSocket.
          </p>
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
    return formatInrCurrency(numValue)
  }

  const totalUnrealizedPnL = parseNumber(portfolio.total_unrealized_pnl)
  const totalRealizedPnL = parseNumber(portfolio.total_realized_pnl)
  const totalPnL = totalUnrealizedPnL + totalRealizedPnL
  const totalValue = parseNumber(portfolio.total_value)
  const isPositive = totalPnL >= 0
  const availableBalance = parseNumber(portfolio.available_balance)
  const marginUsed = parseNumber(portfolio.margin_used)
  const totalEquity = availableBalance + totalUnrealizedPnL

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
                {isPositive ? 'PnL +' : 'PnL '}
                {formatCurrency(totalPnL)}
              </Badge>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 pt-4 border-t">
          <div>
            <div className="text-sm text-muted-foreground mb-1">Available Cash</div>
            <div className="text-xl font-semibold">
              {formatCurrency(availableBalance)}
            </div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground mb-1">Margin Used</div>
            <div className="text-xl font-semibold">
              {formatCurrency(marginUsed)}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {portfolio.open_positions || 0} open
            </div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground mb-1">Unrealized PnL</div>
            <div
              className={cn(
                'text-xl font-semibold',
                totalUnrealizedPnL >= 0 ? 'text-success' : 'text-error'
              )}
            >
              {totalUnrealizedPnL > 0 ? '+' : ''}
              {formatCurrency(totalUnrealizedPnL)}
            </div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground mb-1">Realized PnL</div>
            <div
              className={cn(
                'text-xl font-semibold',
                totalRealizedPnL >= 0 ? 'text-success' : 'text-error'
              )}
            >
              {totalRealizedPnL > 0 ? '+' : ''}
              {formatCurrency(totalRealizedPnL)}
            </div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground mb-1">Total Equity</div>
            <div className="text-xl font-semibold">
              {formatCurrency(totalEquity)}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

