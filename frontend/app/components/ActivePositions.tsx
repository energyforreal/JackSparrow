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
import { formatCurrency, formatUsdCurrency, parseUtcTimestamp } from '@/utils/formatters'

interface ActivePositionsProps {
  positions?: Position[]
  isLoading?: boolean
}

export function ActivePositions({ positions, isLoading = false }: ActivePositionsProps) {
  if (isLoading) {
    return (
      <Card role="status" aria-label="Loading active positions">
        <CardHeader>
          <CardTitle>Active Positions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto -mx-6 px-6 animate-pulse">
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
                {[1, 2, 3, 4, 5].map((row) => (
                  <TableRow key={row}>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-16" />
                    </TableCell>
                    <TableCell>
                      <div className="h-6 bg-muted rounded-md w-12" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-10" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-20" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-20" />
                    </TableCell>
                    <TableCell>
                      <div className="h-6 bg-muted rounded-md w-16" />
                    </TableCell>
                    <TableCell>
                      <div className="h-4 bg-muted rounded-md w-14" />
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

  if (!positions || positions.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Active Positions</CardTitle>
        </CardHeader>
        <CardContent className="rounded-xl border border-dashed p-8 text-center">
          <p className="text-sm text-muted-foreground">No active positions</p>
          <p className="text-xs mt-2 text-muted-foreground/80">
            The agent is monitoring — no open trades right now.
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

  const formatPrice = (price: number | string | undefined) => {
    const numPrice = parseNumber(price)
    return numPrice === null ? 'N/A' : formatUsdCurrency(numPrice)
  }

  const formatQuantity = (quantity: number | string | undefined) => {
    const parsed = parseNumber(quantity)
    if (parsed === null) return 'N/A'
    return parsed.toLocaleString('en-IN', { maximumFractionDigits: 6 })
  }

  const getOpenMinutes = (openedAt: Date | string | null | undefined) => {
    const opened = parseUtcTimestamp(openedAt)
    if (!opened) return null
    const openedMs = opened.getTime()
    const diff = Date.now() - openedMs
    return Math.max(0, Math.floor(diff / (1000 * 60)))
  }

  const getDuration = (openedAt: Date | string | null | undefined) => {
    const totalMin = getOpenMinutes(openedAt)
    if (totalMin === null) return 'N/A'
    const hours = Math.floor(totalMin / 60)
    const minutes = totalMin % 60
    return `${hours}h ${minutes}m`
  }

  function durationClass(minutes: number): string {
    if (minutes < 30) return 'text-green-600 dark:text-green-400'
    if (minutes < 120) return 'text-amber-600 dark:text-amber-400'
    return 'text-red-600 dark:text-red-400'
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Active Positions</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto -mx-6 px-6">
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
                    {formatQuantity(position.quantity)}
                  </TableCell>
                  <TableCell>{formatPrice(position.entry_price_usd ?? position.entry_price)}</TableCell>
                  <TableCell>{formatPrice(position.current_price_usd ?? position.current_price)}</TableCell>
                  <TableCell>
                    {(position.unrealized_pnl_inr !== undefined && position.unrealized_pnl_inr !== null) ||
                    (position.unrealized_pnl !== undefined && position.unrealized_pnl !== null) ? (
                      (() => {
                        const pnl = parseNumber(position.unrealized_pnl_inr ?? position.unrealized_pnl)
                        if (pnl === null) return 'N/A'
                        return (
                      <Badge
                        variant="outline"
                        className={cn(
                          pnl >= 0
                            ? 'text-success border-success'
                            : 'text-error border-error'
                        )}
                      >
                        {pnl > 0 ? '+' : ''}
                        {formatCurrency(pnl)}
                      </Badge>
                        )
                      })()
                    ) : (
                      'N/A'
                    )}
                  </TableCell>
                  <TableCell
                    className={cn(
                      'tabular-nums',
                      durationClass(getOpenMinutes(position.opened_at) ?? 0)
                    )}
                  >
                    {getDuration(position.opened_at)}
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

