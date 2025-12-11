'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Signal, SignalType, Trade } from '@/types'
import { cn } from '@/lib/utils'
import { formatConfidence, formatDateTime } from '@/utils/formatters'
import { DataFreshnessIndicator } from './DataFreshnessIndicator'

interface TradingDecisionProps {
  signal?: Signal | null
  recentTrade?: Trade | null
  paperTradingMode: boolean
}

const getSignalBadgeClasses = (signal: SignalType) => {
  switch (signal) {
    case 'STRONG_BUY':
      return 'bg-emerald-700 text-white hover:bg-emerald-800'
    case 'BUY':
      return 'bg-success text-white hover:bg-success/90'
    case 'HOLD':
      return 'bg-muted text-muted-foreground'
    case 'SELL':
      return 'bg-error text-white hover:bg-error/90'
    case 'STRONG_SELL':
      return 'bg-red-800 text-white hover:bg-red-900'
    default:
      return ''
  }
}

const getDecisionAction = (signal: SignalType): string => {
  switch (signal) {
    case 'STRONG_BUY':
    case 'BUY':
      return 'Enter Long Position'
    case 'STRONG_SELL':
    case 'SELL':
      return 'Enter Short Position'
    case 'HOLD':
      return 'Wait for Better Opportunity'
    default:
      return 'No Action'
  }
}

const formatPrice = (price: number | string | undefined) => {
  if (price === undefined || price === null) return 'N/A'
  const numPrice = typeof price === 'string' ? parseFloat(price) : price
  if (isNaN(numPrice)) return 'N/A'
  return `$${numPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const formatDate = (date: Date | string) => {
  return formatDateTime(date)
}

export function TradingDecision({
  signal,
  recentTrade,
  paperTradingMode,
}: TradingDecisionProps) {
  const hasSignal = signal && signal.signal
  const hasRecentTrade = recentTrade !== null && recentTrade !== undefined

  return (
    <Card role="region" aria-label="Trading Decision Flow">
      <CardHeader>
        <CardTitle>Trading Decision Flow</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Current Decision */}
        <div className="space-y-3">
          <h3 className="text-sm font-semibold">Current Decision</h3>
          
          {hasSignal ? (
            <div className="space-y-3 p-4 rounded-lg border bg-card">
              <div className="flex items-center gap-4">
                <Badge
                  className={cn(
                    'px-4 py-2 text-base',
                    getSignalBadgeClasses(signal.signal)
                  )}
                >
                  {signal.signal.replace('_', ' ')}
                </Badge>
                <div className="flex-1">
                  <div className="text-sm font-medium">
                    {getDecisionAction(signal.signal)}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Confidence: {formatConfidence(signal.confidence)}
                  </div>
                </div>
              </div>

              {signal.symbol && (
                <div className="text-sm text-muted-foreground">
                  Symbol: <span className="font-medium">{signal.symbol}</span>
                </div>
              )}

              {signal.agent_decision_reasoning && (
                <div className="pt-2 border-t">
                  <p className="text-xs font-medium mb-1">Decision Reasoning</p>
                  <p className="text-xs text-muted-foreground">
                    {signal.agent_decision_reasoning}
                  </p>
                </div>
              )}

              {signal.timestamp && (
                <DataFreshnessIndicator 
                  timestamp={signal.timestamp} 
                  label="Decision time"
                />
              )}
            </div>
          ) : (
            <div className="p-4 rounded-lg border bg-muted/50">
              <p className="text-sm text-muted-foreground">
                No trading decision available
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Waiting for signal from agent. Ensure agent service is running.
              </p>
            </div>
          )}
        </div>

        {/* Recent Trade Connection */}
        {hasRecentTrade && (
          <div className="space-y-3 pt-2 border-t">
            <h3 className="text-sm font-semibold">Related Trade</h3>
            <div className="p-4 rounded-lg border bg-card">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <span className="text-muted-foreground">Trade ID:</span>
                  <span className="ml-2 font-medium font-mono text-xs">
                    {recentTrade.trade_id}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Symbol:</span>
                  <span className="ml-2 font-medium">{recentTrade.symbol}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">Side:</span>
                  <Badge
                    variant={recentTrade.side === 'BUY' ? 'default' : 'destructive'}
                    className="ml-2"
                  >
                    {recentTrade.side}
                  </Badge>
                </div>
                <div>
                  <span className="text-muted-foreground">Quantity:</span>
                  <span className="ml-2 font-medium">
                    {typeof recentTrade.quantity === 'string'
                      ? parseFloat(recentTrade.quantity).toLocaleString()
                      : recentTrade.quantity.toLocaleString()}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Price:</span>
                  <span className="ml-2 font-medium">
                    {formatPrice(recentTrade.price)}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Status:</span>
                  <Badge
                    variant={
                      recentTrade.status === 'filled' || recentTrade.status === 'closed'
                        ? 'default'
                        : 'secondary'
                    }
                    className="ml-2"
                  >
                    {recentTrade.status.toUpperCase()}
                  </Badge>
                </div>
                <div className="col-span-2">
                  <span className="text-muted-foreground">Executed at:</span>
                  <span className="ml-2 font-medium text-xs">
                    {formatDate(recentTrade.executed_at)}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

      </CardContent>
    </Card>
  )
}
