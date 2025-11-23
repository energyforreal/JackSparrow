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
import { Position } from '@/types'
import { cn } from '@/lib/utils'
import { LoadingSpinner, LoadingSkeleton } from './LoadingSpinner'

interface ActivePositionsProps {
  positions?: Position[]
  isLoading?: boolean
}

export function ActivePositions({ positions, isLoading = false }: ActivePositionsProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Active Positions</CardTitle>
        </CardHeader>
        <CardContent>
          <LoadingSkeleton className="py-4" />
        </CardContent>
      </Card>
    )
  }

  if (!positions || positions.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Active Positions</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No active positions</p>
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
    return new Date(date).toLocaleString()
  }

  const getDuration = (openedAt: Date | string) => {
    const now = new Date()
    const diff = now.getTime() - new Date(openedAt).getTime()
    const hours = Math.floor(diff / (1000 * 60 * 60))
    const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))
    return `${hours}h ${minutes}m`
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Active Positions</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Symbol</TableHead>
              <TableHead>Side</TableHead>
              <TableHead>Quantity</TableHead>
              <TableHead>Entry Price</TableHead>
              <TableHead>Current Price</TableHead>
              <TableHead>PnL</TableHead>
              <TableHead>Duration</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {positions.map((position) => (
              <TableRow key={position.position_id}>
                <TableCell className="font-medium">{position.symbol}</TableCell>
                <TableCell>
                  <Badge
                    variant={position.side === 'BUY' ? 'default' : 'destructive'}
                  >
                    {position.side}
                  </Badge>
                </TableCell>
                <TableCell>
                  {typeof position.quantity === 'string' 
                    ? parseFloat(position.quantity).toLocaleString()
                    : position.quantity.toLocaleString()}
                </TableCell>
                <TableCell>{formatPrice(position.entry_price)}</TableCell>
                <TableCell>{formatPrice(position.current_price)}</TableCell>
                <TableCell>
                  {position.unrealized_pnl !== undefined && position.unrealized_pnl !== null ? (
                    <Badge
                      variant="outline"
                      className={cn(
                        (typeof position.unrealized_pnl === 'string' 
                          ? parseFloat(position.unrealized_pnl) 
                          : position.unrealized_pnl) >= 0
                          ? 'text-success border-success'
                          : 'text-error border-error'
                      )}
                    >
                      {(typeof position.unrealized_pnl === 'string' 
                        ? parseFloat(position.unrealized_pnl) 
                        : position.unrealized_pnl) >= 0 ? '+' : ''}
                      {formatPrice(position.unrealized_pnl)}
                    </Badge>
                  ) : (
                    'N/A'
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {getDuration(position.opened_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

