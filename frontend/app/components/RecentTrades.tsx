'use client'

import { useState, useRef, useEffect } from 'react'
import type { RecentTradesMeta } from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Trade } from '@/types'
import { formatCurrency, formatDateTime, formatUsdCurrency } from '@/utils/formatters'
import {
  computeTradeDurationSeconds,
  formatTradeDuration,
  isExchangeFillTrade,
  isLongSide,
  parseFiniteNumber,
  resolveContractValueBtc,
  resolveUsdInrRate,
  sideBadgeVariant,
} from '@/utils/tradingDisplay'

const INITIAL_VISIBLE_TRADES = 10
const VISIBLE_TRADES_STEP = 10

const TABLE_HEADS = [
  'Entry Time',
  'Exit Time',
  'Duration',
  'Side',
  'Symbol',
  'Quantity',
  'Entry Price',
  'Exit Price',
  'PnL',
  'Order ID',
  'Fill ID',
  'Role',
  'Commission',
  'Type',
  'Record',
  'Exit reason',
  'Status',
] as const

interface RecentTradesProps {
  trades?: Trade[]
  isLoading?: boolean
  tradesMeta?: RecentTradesMeta | null
  tradesError?: string | null
  usdInrRate?: number | string
  contractValueBtc?: number | string
}

function truncateId(id: string | undefined, max = 10): string {
  if (!id) return '—'
  return id.length > max ? `${id.slice(0, max)}…` : id
}

export function RecentTrades({
  trades,
  isLoading = false,
  tradesMeta,
  tradesError,
  usdInrRate,
  contractValueBtc,
}: RecentTradesProps) {
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE_TRADES)
  const prevTradeCountRef = useRef(0)
  const tradeCount = trades?.length ?? 0
  const ariaLiveActive = tradeCount > prevTradeCountRef.current

  useEffect(() => {
    prevTradeCountRef.current = tradeCount
  }, [tradeCount])

  if (isLoading) {
    return (
      <Card role="status" aria-label="Loading recent trades">
        <CardHeader>
          <CardTitle>Agent trades</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto -mx-6 px-6 animate-pulse">
            <Table>
              <TableHeader>
                <TableRow>
                  {TABLE_HEADS.map((head) => (
                    <TableHead key={head} scope="col">
                      {head}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {[1, 2, 3, 4, 5].map((row) => (
                  <TableRow key={row}>
                    {TABLE_HEADS.map((head) => (
                      <TableCell key={head}>
                        <MotionSkeletonBar className="h-4 w-14" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (tradesError) {
    return (
      <Card role="alert">
        <CardHeader>
          <CardTitle>Agent trades</CardTitle>
        </CardHeader>
        <CardContent className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center">
          <p className="text-sm text-destructive font-medium">Could not load recent trades</p>
          <p className="text-xs mt-2 text-muted-foreground break-all">{tradesError}</p>
        </CardContent>
      </Card>
    )
  }

  if (!trades || trades.length === 0) {
    const suppressed = tradesMeta?.suppressed === true
    return (
      <Card>
        <CardHeader>
          <CardTitle>Agent trades</CardTitle>
        </CardHeader>
        <CardContent className="rounded-xl border border-dashed p-8 text-center">
          <p className="text-sm text-muted-foreground">
            {suppressed
              ? 'Recent trades display is suppressed'
              : 'No agent-executed trades yet'}
          </p>
          <p className="text-xs mt-2 text-muted-foreground/80">
            {suppressed
              ? 'Clear the suppress flag or unset SUPPRESS_RECENT_TRADES to show history again.'
              : 'Closed round-trips and Delta testnet fills (agent orders) sync here when trades execute.'}
          </p>
        </CardContent>
      </Card>
    )
  }

  const usdInr = resolveUsdInrRate(usdInrRate)
  const contractBtc = resolveContractValueBtc(contractValueBtc) ?? 0.001
  const totalTrades = trades.length
  const visibleTrades = trades.slice(0, visibleCount)
  const hasMore = visibleCount < totalTrades

  const formatQuantity = (quantity: number | string | undefined) => {
    const parsed = parseFiniteNumber(quantity)
    if (parsed === null) return 'N/A'
    return parsed.toLocaleString('en-IN', { maximumFractionDigits: 6 })
  }

  const formatTradeTimestamp = (date: Date | string | undefined) => {
    if (!date) return '—'
    return formatDateTime(date)
  }

  const formatPriceUsd = (price: number | string | undefined) => {
    const parsed = parseFiniteNumber(price)
    if (parsed === null) return '—'
    return formatUsdCurrency(parsed)
  }

  const formatPnl = (trade: Trade): number | null => {
    if (isExchangeFillTrade(trade as Record<string, unknown>)) return null
    const directPnl = parseFiniteNumber(trade.pnl)
    if (directPnl !== null) return directPnl
    const pnlUsd = parseFiniteNumber(trade.pnl_usd)
    if (pnlUsd !== null) {
      if (usdInr === null) return null
      return pnlUsd * usdInr
    }
    const entry = parseFiniteNumber(trade.entry_price)
    const exit = parseFiniteNumber(trade.exit_price ?? trade.price)
    const quantity = parseFiniteNumber(trade.quantity)
    if (entry === null || exit === null || quantity === null || usdInr === null) return null
    const gross = isLongSide(trade.side)
      ? (exit - entry) * quantity
      : (entry - exit) * quantity
    return gross * contractBtc * usdInr
  }

  const formatCommission = (trade: Trade): string => {
    const commission = parseFiniteNumber(trade.commission_usd)
    if (commission === null) return '—'
    return formatUsdCurrency(commission)
  }

  const formatFillType = (trade: Trade): string => {
    const fillType = trade.fill_type
    const orderType = trade.order_type
    if (fillType && orderType) return `${fillType} / ${orderType}`
    return fillType || orderType || '—'
  }

  const formatRecordKind = (trade: Trade): string => {
    if (isExchangeFillTrade(trade as Record<string, unknown>)) return 'Fill'
    if (trade.record_kind === 'round_trip') return 'Round-trip'
    return 'Round-trip'
  }

  const formatExitReason = (trade: Trade): string => {
    const reason = trade.exit_reason
    if (!reason) return '—'
    return String(reason).replace(/_/g, ' ')
  }

  const getStatusVariant = (status: string) => {
    switch (status.toLowerCase()) {
      case 'closed':
      case 'filled':
        return 'default'
      case 'pending':
        return 'secondary'
      case 'cancelled':
        return 'destructive'
      default:
        return 'outline'
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0">
        <CardTitle>Agent trades</CardTitle>
        <p className="text-xs text-muted-foreground tabular-nums">
          Showing {visibleTrades.length} of {totalTrades}
        </p>
      </CardHeader>
      <CardContent>
        {tradesMeta?.fills_attribution === 'all_fills' && (
          <p className="text-xs text-muted-foreground mb-3 px-1">
            Showing all testnet fills (agent order IDs not found in recent history).
          </p>
        )}
        <div
          className="overflow-x-auto -mx-6 px-6"
          aria-live={ariaLiveActive ? 'polite' : 'off'}
          aria-atomic="false"
        >
          <Table>
            <TableHeader>
              <TableRow>
                {TABLE_HEADS.map((head) => (
                  <TableHead key={head} scope="col">
                    {head}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleTrades.map((trade) => {
                const isFill = isExchangeFillTrade(trade as Record<string, unknown>)
                const entryTime = trade.entry_time as Date | string | undefined
                const exitTime = (trade.exit_time ?? trade.executed_at ?? trade.timestamp) as
                  | Date
                  | string
                const durationSec = isFill
                  ? null
                  : computeTradeDurationSeconds(trade.duration_seconds, entryTime, exitTime)
                const fillPrice = trade.exit_price ?? trade.price ?? trade.fill_price

                return (
                  <TableRow key={trade.trade_id}>
                    <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                      {isFill ? '—' : formatTradeTimestamp(entryTime)}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs whitespace-nowrap">
                      {formatTradeTimestamp(exitTime)}
                    </TableCell>
                    <TableCell>{isFill ? '—' : formatTradeDuration(durationSec)}</TableCell>
                    <TableCell>
                      <Badge variant={sideBadgeVariant(trade.side)}>{trade.side}</Badge>
                    </TableCell>
                    <TableCell className="font-medium">{trade.symbol}</TableCell>
                    <TableCell>{formatQuantity(trade.quantity)}</TableCell>
                    <TableCell>{isFill ? '—' : formatPriceUsd(trade.entry_price)}</TableCell>
                    <TableCell>{formatPriceUsd(fillPrice)}</TableCell>
                    <TableCell>
                      {(() => {
                        const pnl = formatPnl(trade)
                        if (pnl === null) return '—'
                        const pnlClass = pnl >= 0 ? 'text-emerald-600' : 'text-red-600'
                        return (
                          <span className={`font-medium ${pnlClass}`}>{formatCurrency(pnl)}</span>
                        )
                      })()}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {truncateId(trade.exchange_order_id)}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {truncateId(trade.fill_id)}
                    </TableCell>
                    <TableCell className="text-xs capitalize text-muted-foreground">
                      {trade.role ?? '—'}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatCommission(trade)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatFillType(trade)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {formatRecordKind(trade)}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground capitalize">
                      {isFill ? '—' : formatExitReason(trade)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={getStatusVariant(trade.status ?? 'CLOSED')}>
                        {trade.status ?? 'CLOSED'}
                      </Badge>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
        {hasMore && (
          <div className="mt-4 flex justify-center">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setVisibleCount((count) => Math.min(count + VISIBLE_TRADES_STEP, totalTrades))
              }
            >
              Show more ({totalTrades - visibleCount} remaining)
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function MotionSkeletonBar({ className }: { className: string }) {
  return <div className={`bg-muted rounded-md ${className}`} aria-hidden />
}
