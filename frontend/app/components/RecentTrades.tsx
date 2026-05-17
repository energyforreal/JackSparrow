'use client'

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
import { Trade } from '@/types'
import { formatClockTime, formatCurrency, formatUsdCurrency } from '@/utils/formatters'
import {
  computeTradeDurationSeconds,
  formatTradeDuration,
  isLongSide,
  parseFiniteNumber,
  resolveContractValueBtc,
  resolveUsdInrRate,
  sideBadgeVariant,
} from '@/utils/tradingDisplay'

interface RecentTradesProps {
  trades?: Trade[]
  isLoading?: boolean
  usdInrRate?: number | string
  contractValueBtc?: number | string
}

export function RecentTrades({
  trades,
  isLoading = false,
  usdInrRate,
  contractValueBtc,
}: RecentTradesProps) {
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
                  <TableHead>Entry Time</TableHead>
                  <TableHead>Exit Time</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Quantity</TableHead>
                  <TableHead>Entry Price</TableHead>
                  <TableHead>Exit Price</TableHead>
                  <TableHead>PnL</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[1, 2, 3, 4, 5].map((row) => (
                  <TableRow key={row}>
                    <TableCell>
                      <motionSkeletonBar className="h-4 w-14" />
                    </TableCell>
                    <TableCell>
                      <motionSkeletonBar className="h-4 w-14" />
                    </TableCell>
                    <TableCell>
                      <motionSkeletonBar className="h-4 w-10" />
                    </TableCell>
                    <TableCell>
                      <motionSkeletonBar className="h-6 w-12" />
                    </TableCell>
                    <TableCell>
                      <motionSkeletonBar className="h-4 w-16" />
                    </TableCell>
                    <TableCell>
                      <motionSkeletonBar className="h-4 w-10" />
                    </TableCell>
                    <TableCell>
                      <motionSkeletonBar className="h-4 w-16" />
                    </TableCell>
                    <TableCell>
                      <motionSkeletonBar className="h-4 w-16" />
                    </TableCell>
                    <TableCell>
                      <motionSkeletonBar className="h-6 w-16" />
                    </TableCell>
                    <TableCell>
                      <motionSkeletonBar className="h-6 w-16" />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!trades || trades.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Agent trades</CardTitle>
        </CardHeader>
        <CardContent className="rounded-xl border border-dashed p-8 text-center">
          <p className="text-sm text-muted-foreground">No agent-executed closed trades yet</p>
          <p className="text-xs mt-2 text-muted-foreground/80">
            Round-trip trades closed by Jack Sparrow will appear here with entry, exit, and PnL.
          </p>
        </CardContent>
      </Card>
    )
  }

  const usdInr = resolveUsdInrRate(usdInrRate)
  const contractBtc = resolveContractValueBtc(contractValueBtc) ?? 0.001

  const formatQuantity = (quantity: number | string | undefined) => {
    const parsed = parseFiniteNumber(quantity)
    if (parsed === null) return 'N/A'
    return parsed.toLocaleString('en-IN', { maximumFractionDigits: 6 })
  }

  const formatDate = (date: Date | string) => formatClockTime(date)

  const formatPriceUsd = (price: number | string | undefined) => {
    const parsed = parseFiniteNumber(price)
    if (parsed === null) return 'N/A'
    return formatUsdCurrency(parsed)
  }

  const formatPnl = (trade: Trade): number | null => {
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
      <CardHeader>
        <CardTitle>Agent trades</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto -mx-6 px-6">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Entry Time</TableHead>
                <TableHead>Exit Time</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Side</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Quantity</TableHead>
                <TableHead>Entry Price</TableHead>
                <TableHead>Exit Price</TableHead>
                <TableHead>PnL</TableHead>
                <TableHead>Order ID</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {trades.slice(0, 10).map((trade) => {
                const entryTime = (trade.entry_time ?? trade.executed_at ?? trade.timestamp) as
                  | Date
                  | string
                const exitTime = (trade.exit_time ?? trade.executed_at ?? trade.timestamp) as
                  | Date
                  | string
                const durationSec = computeTradeDurationSeconds(
                  trade.duration_seconds,
                  entryTime,
                  exitTime
                )
                return (
                  <TableRow key={trade.trade_id}>
                    <TableCell className="text-muted-foreground">{formatDate(entryTime)}</TableCell>
                    <TableCell className="text-muted-foreground">{formatDate(exitTime)}</TableCell>
                    <TableCell>{formatTradeDuration(durationSec)}</TableCell>
                    <TableCell>
                      <Badge variant={sideBadgeVariant(trade.side)}>{trade.side}</Badge>
                    </TableCell>
                    <TableCell className="font-medium">{trade.symbol}</TableCell>
                    <TableCell>{formatQuantity(trade.quantity)}</TableCell>
                    <TableCell>{formatPriceUsd(trade.entry_price)}</TableCell>
                    <TableCell>{formatPriceUsd(trade.exit_price ?? trade.price)}</TableCell>
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
                      {trade.exchange_order_id
                        ? trade.exchange_order_id.length > 10
                          ? `${trade.exchange_order_id.slice(0, 10)}…`
                          : trade.exchange_order_id
                        : '—'}
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
      </CardContent>
    </Card>
  )
}

function motionSkeletonBar({ className }: { className: string }) {
  return <div className={`bg-muted rounded-md ${className}`} aria-hidden />
}
