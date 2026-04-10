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
                  <TableHead>Time</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Quantity</TableHead>
                  <TableHead>Trade Value</TableHead>
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
                      <div className="h-6 bg-muted rounded-md w-12" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-16" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-10" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-20" />
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
          <p className="text-sm text-muted-foreground">No recent trades</p>
          <p className="text-xs mt-2 text-muted-foreground/80">
            Executions will appear here after the agent places paper trades.
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

  const formatTradeValueInr = (trade: Trade) => {
    const explicit = parseNumber(trade.trade_value_inr)
    if (explicit !== null) return formatCurrency(explicit)
    const quantity = parseNumber(trade.quantity)
    const priceUsd = parseNumber(trade.price ?? trade.fill_price)
    if (quantity === null || priceUsd === null) return 'N/A'
    const valueInr = quantity * priceUsd * contractValueBtc * usdInr
    return formatCurrency(valueInr)
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
                <TableHead>Time</TableHead>
                <TableHead>Side</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Quantity</TableHead>
                <TableHead>Trade Value</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {trades.slice(0, 10).map((trade) => (
                <TableRow key={trade.trade_id}>
                  <TableCell className="text-muted-foreground">
                    {formatDate(trade.executed_at ?? trade.timestamp)}
                  </TableCell>
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
                  <TableCell>{formatTradeValueInr(trade)}</TableCell>
                  <TableCell>
                    <Badge variant={getStatusVariant(trade.status ?? 'EXECUTED')}>
                      {trade.status ?? 'EXECUTED'}
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

