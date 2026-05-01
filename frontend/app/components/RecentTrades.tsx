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
import { formatClockTime, formatCurrency } from '@/utils/formatters'

interface RecentTradesProps {
  trades?: Trade[]
  isLoading?: boolean
  usdInrRate?: number | string
}

export function RecentTrades({ trades, isLoading = false, usdInrRate }: RecentTradesProps) {
  if (isLoading) {
    return (
      <Card role="status" aria-label="Loading recent trades">
        <CardHeader>
          <CardTitle>Recent Trades</CardTitle>
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
                      <div className="h-4 bg-muted rounded-md w-14" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-14" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-10" />
                    </TableCell>
                    <TableCell>
                      <div className="h-6 bg-muted rounded-md w-12" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-16" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-10" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-16" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-16" />
                    </TableCell>
                    <TableCell>
                      <div className="h-6 bg-muted rounded-md w-16" />
                    </TableCell>
                    <TableCell>
                      <div className="h-6 bg-muted rounded-md w-16" />
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
          <CardTitle>Recent Trades</CardTitle>
        </CardHeader>
        <CardContent className="rounded-xl border border-dashed p-8 text-center">
          <p className="text-sm text-muted-foreground">No closed trades yet</p>
          <p className="text-xs mt-2 text-muted-foreground/80">
            Completed trades with entry/exit analytics will appear here.
          </p>
        </CardContent>
      </Card>
    )
  }

  const parseNumber = (value: number | string | undefined): number | null => {
    if (value === undefined || value === null) return null
    const parsed = typeof value === 'number' ? value : parseFloat(value)
    return Number.isFinite(parsed) ? parsed : null
  }

  const usdInr = (() => {
    const parsed = parseNumber(usdInrRate)
    return parsed && parsed > 0 ? parsed : 83
  })()

  const contractValueBtc = 0.001

  const formatDuration = (durationSeconds: number | undefined): string => {
    if (!durationSeconds || durationSeconds < 0) return '0s'
    const hours = Math.floor(durationSeconds / 3600)
    const minutes = Math.floor((durationSeconds % 3600) / 60)
    const seconds = durationSeconds % 60
    if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`
    if (minutes > 0) return `${minutes}m ${seconds}s`
    return `${seconds}s`
  }

  const formatQuantity = (quantity: number | string | undefined) => {
    if (quantity === undefined || quantity === null) return 'N/A'
    const parsed = typeof quantity === 'number' ? quantity : parseFloat(quantity)
    if (!Number.isFinite(parsed)) return 'N/A'
    return parsed.toLocaleString('en-IN', { maximumFractionDigits: 6 })
  }

  const formatDate = (date: Date | string) => {
    return formatClockTime(date)
  }

  const formatPriceInr = (price: number | string | undefined) => {
    const parsed = parseNumber(price)
    if (parsed === null) return 'N/A'
    return formatCurrency(parsed * contractValueBtc * usdInr)
  }

  const formatPnl = (trade: Trade) => {
    const directPnl = parseNumber(trade.pnl)
    if (directPnl !== null) return directPnl
    const pnlUsd = parseNumber(trade.pnl_usd)
    if (pnlUsd !== null) return pnlUsd * usdInr
    const entry = parseNumber(trade.entry_price)
    const exit = parseNumber(trade.exit_price ?? trade.price)
    const quantity = parseNumber(trade.quantity)
    if (entry === null || exit === null || quantity === null) return null
    const side = String(trade.side || '').toUpperCase()
    const gross = side === 'SELL' || side === 'SHORT'
      ? (entry - exit) * quantity
      : (exit - entry) * quantity
    return gross * contractValueBtc * usdInr
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
        <CardTitle>Recent Trades</CardTitle>
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
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {trades.slice(0, 10).map((trade) => (
                <TableRow key={trade.trade_id}>
                  <TableCell className="text-muted-foreground">
                    {formatDate((trade.entry_time ?? trade.executed_at ?? trade.timestamp) as Date | string)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate((trade.exit_time ?? trade.executed_at ?? trade.timestamp) as Date | string)}
                  </TableCell>
                  <TableCell>{formatDuration(trade.duration_seconds)}</TableCell>
                  <TableCell>
                    <Badge
                      variant={trade.side === 'BUY' ? 'default' : 'destructive'}
                    >
                      {trade.side}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-medium">{trade.symbol}</TableCell>
                  <TableCell>
                    {formatQuantity(trade.quantity)}
                  </TableCell>
                  <TableCell>{formatPriceInr(trade.entry_price)}</TableCell>
                  <TableCell>{formatPriceInr(trade.exit_price ?? trade.price)}</TableCell>
                  <TableCell>
                    {(() => {
                      const pnl = formatPnl(trade)
                      if (pnl === null) return 'N/A'
                      const pnlClass = pnl >= 0 ? 'text-emerald-600' : 'text-red-600'
                      return <span className={`font-medium ${pnlClass}`}>{formatCurrency(pnl)}</span>
                    })()}
                  </TableCell>
                  <TableCell>
                    <Badge variant={getStatusVariant(trade.status ?? 'CLOSED')}>
                      {trade.status ?? 'CLOSED'}
                    </Badge>
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

