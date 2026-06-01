'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Signal, SignalType, Trade } from '@/types'
import { cn } from '@/lib/utils'
import { formatConfidence, formatCurrency, formatDateTime } from '@/utils/formatters'
import {
  parseFiniteNumber,
  resolveContractValueBtc,
  resolveUsdInrRate,
  sideBadgeVariant,
} from '@/utils/tradingDisplay'
import { DataFreshnessIndicator } from './DataFreshnessIndicator'

interface TradingDecisionProps {
  signal?: Signal | null
  recentTrade?: Trade | null
  exchangeEnvironment?: string
  usdInrRate?: number | string
  contractValueBtc?: number | string
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

const formatDate = (date: Date | string) => {
  return formatDateTime(date)
}

const formatQuantity = (quantity: number | string | undefined) => {
  if (quantity === undefined || quantity === null) return 'N/A'
  const parsed = typeof quantity === 'number' ? quantity : parseFloat(quantity)
  if (!Number.isFinite(parsed)) return 'N/A'
  return parsed.toLocaleString('en-IN', { maximumFractionDigits: 6 })
}

export function TradingDecision({
  signal,
  recentTrade,
  exchangeEnvironment,
  usdInrRate,
  contractValueBtc,
}: TradingDecisionProps) {
  const hasSignal = signal && signal.signal
  const hasRecentTrade = recentTrade !== null && recentTrade !== undefined

  const formatTradeValueInr = (trade: Trade) => {
    const explicit = parseFiniteNumber(trade.trade_value_inr)
    if (explicit !== null) return formatCurrency(explicit)
    const quantity = parseFiniteNumber(trade.quantity)
    const priceUsd = parseFiniteNumber(trade.price ?? trade.fill_price ?? trade.entry_price)
    const fx =
      resolveUsdInrRate((trade as Trade & { usd_inr_rate?: number }).usd_inr_rate) ??
      resolveUsdInrRate(usdInrRate)
    const contractBtc = resolveContractValueBtc(contractValueBtc) ?? 0.001
    if (quantity === null || priceUsd === null || fx === null) return '—'
    const valueInr = quantity * priceUsd * contractBtc * fx
    return formatCurrency(valueInr)
  }

  return (
    <Card role="region" aria-label="Trading Decision Flow">
      <CardHeader>
        <CardTitle>Trading Decision Flow</CardTitle>
        {(exchangeEnvironment === 'testnet' ||
          exchangeEnvironment === 'india_testnet') && (
          <p className="text-xs text-muted-foreground mt-1">
            Executing on Delta testnet
          </p>
        )}
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
            <div className="p-4 rounded-lg border bg-muted/50 space-y-3">
              <p className="text-sm text-muted-foreground">
                No trading decision available
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Ensure backend and agent services are running.
              </p>
              
            </div>
          )}
        </div>

        {/* Recent Trade Connection */}
        {hasRecentTrade && (
          <div className="space-y-3 pt-2 border-t">
            <h3 className="text-sm font-semibold">Latest fill</h3>
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
                  <Badge variant={sideBadgeVariant(recentTrade.side)} className="ml-2">
                    {recentTrade.side}
                  </Badge>
                </div>
                <div>
                  <span className="text-muted-foreground">Quantity:</span>
                  <span className="ml-2 font-medium">
                    {formatQuantity(recentTrade.quantity)}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Trade Value:</span>
                  <span className="ml-2 font-medium">
                    {formatTradeValueInr(recentTrade)}
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
                {recentTrade.exchange_order_id ? (
                  <div className="col-span-2">
                    <span className="text-muted-foreground">Exchange order:</span>
                    <span className="ml-2 font-medium font-mono text-xs">
                      {recentTrade.exchange_order_id}
                    </span>
                  </div>
                ) : null}
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
