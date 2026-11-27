'use client'

import { Badge } from '@/components/ui/badge'
import type { Signal } from '@/types'
import { isAlgorithmicPath } from '@/utils/signalConfidence'

const TIMEFRAME_ROWS: Array<{
  frame: '4h' | '1h' | '15m' | '5m'
  label: string
  field: string
}> = [
  { frame: '4h', label: 'Trend', field: 'trend' },
  { frame: '1h', label: 'Structure', field: 'structure' },
  { frame: '1h', label: 'Zone', field: 'zone' },
  { frame: '15m', label: 'Pattern', field: 'pattern' },
  { frame: '5m', label: 'Confirmation', field: 'confirmation' },
  { frame: '5m', label: 'Volume', field: 'volume' },
  { frame: '5m', label: 'Momentum', field: 'momentum' },
]

function formatPoint(value: number | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function formatPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value)) || Number(value) <= 0) return '—'
  return Number(value).toLocaleString('en-US', { maximumFractionDigits: 2 })
}

interface AlgorithmicVerdictProps {
  signal: Signal
}

/** Score, timeframe points, and authorization for the algorithmic path. */
export function AlgorithmicVerdict({ signal }: AlgorithmicVerdictProps) {
  if (!isAlgorithmicPath(signal)) return null
  const decision = signal.trading_decision
  const frames = decision?.market_context
  const score = decision?.score
  const authorized = decision?.execution_authorized === true

  return (
    <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2 space-y-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium text-foreground text-sm">Algorithmic score</p>
        <Badge variant={authorized ? 'default' : 'outline'} className="text-[10px] font-normal">
          {authorized ? 'Orders authorized' : 'Orders not authorized'}
        </Badge>
      </div>
      <p className="text-muted-foreground">
        Score{' '}
        <span className="font-medium text-foreground tabular-nums">
          {score == null || !Number.isFinite(Number(score)) ? '—' : formatPoint(Number(score))}
        </span>
        . Position size is set by risk configuration.
      </p>
      {frames && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {TIMEFRAME_ROWS.map((row) => {
            const point = frames[row.frame]?.[row.field]
            return (
              <div key={`${row.frame}-${row.field}`}>
                <p className="text-muted-foreground">
                  {row.frame} {row.label}
                </p>
                <p className="font-medium tabular-nums text-foreground">{formatPoint(point)}</p>
              </div>
            )
          })}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-muted-foreground">Proposed stop</p>
          <p className="font-medium tabular-nums text-foreground">
            {formatPrice(decision?.risk?.stop_loss)}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground">Proposed target</p>
          <p className="font-medium tabular-nums text-foreground">
            {formatPrice(decision?.risk?.take_profit)}
          </p>
        </div>
      </div>
      {(decision?.decision_id || decision?.candle_timestamp) && (
        <p className="text-[10px] text-muted-foreground break-all">
          {decision.decision_id ? `Decision ${decision.decision_id}` : ''}
          {decision.decision_id && decision.candle_timestamp ? ' · ' : ''}
          {decision.candle_timestamp ? `Candle ${decision.candle_timestamp}` : ''}
        </p>
      )}
    </div>
  )
}
