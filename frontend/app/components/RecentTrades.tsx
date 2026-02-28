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
import { formatClockTime } from '@/utils/formatters'

interface RecentTradesProps {
  trades?: Trade[]
}

export function RecentTrades({ trades }: RecentTradesProps) {
  if (!trades || trades.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Trades</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No recent trades</p>
        </CardContent>
      </Card>
    )
  }

  const formatPrice = (price: number | string | undefined) => {
    if (price === undefined || price === null) return 'N/A'
    const numPrice = typeof price === 'string' ? parseFloat(price) : price
    if (isNaN(numPrice)) return 'N/A'
    return `$${numPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
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
                <TableHead>Price</TableHead>
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
                    {typeof trade.quantity === 'string' 
                      ? parseFloat(trade.quantity).toLocaleString()
                      : trade.quantity.toLocaleString()}
                  </TableCell>
                  <TableCell>{formatPrice(trade.price ?? trade.fill_price)}</TableCell>
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

