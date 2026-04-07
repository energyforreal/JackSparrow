'use client'

import { cn } from '@/lib/utils'

interface EdgeGaugeProps {
  edge: number
  className?: string
}

/** Map edge roughly in [-1, 1] to a horizontal bar. */
export function EdgeGauge({ edge, className }: EdgeGaugeProps) {
  const clamped = Math.max(-1, Math.min(1, edge))
  const pct = ((clamped + 1) / 2) * 100
  return (
    <div className={cn('space-y-1', className)}>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>Sell</span>
        <span>Edge {clamped.toFixed(3)}</span>
        <span>Buy</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className="h-full bg-primary transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
