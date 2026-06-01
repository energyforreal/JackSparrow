'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ConfidenceProgress } from './ConfidenceProgress'
import { Signal, SignalType, ReflectionSnapshot } from '@/types'
import { cn } from '@/lib/utils'
import { formatConfidence } from '@/utils/formatters'
import { resolveDisplayConfidence } from '@/utils/signalConfidence'
import { DataFreshnessIndicator } from './DataFreshnessIndicator'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface SignalIndicatorProps {
  signal?: Signal
  lastReflection?: ReflectionSnapshot | null
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

const getSignalIcon = (signal: SignalType) => {
  switch (signal) {
    case 'STRONG_BUY':
    case 'BUY':
      return <TrendingUp className="h-4 w-4" />
    case 'STRONG_SELL':
    case 'SELL':
      return <TrendingDown className="h-4 w-4" />
    default:
      return <Minus className="h-4 w-4" />
  }
}

export function SignalIndicator({ signal, lastReflection }: SignalIndicatorProps) {
  if (!signal) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Trading Signal</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No signal available</p>
          <p className="text-xs text-muted-foreground mt-2">
            Signals appear after a full prediction cycle (market data → features → analysis). Press{' '}
            <kbd className="px-1 rounded border border-border">P</kbd> for a manual prediction.
          </p>
        </CardContent>
      </Card>
    )
  }

  const displayConfidence = resolveDisplayConfidence(signal)
  const overallConfidence = displayConfidence.percent
  const policyConfidencePercent = displayConfidence.policyPercent

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Trading Signal</CardTitle>
          {signal.regime && (
            <Badge variant="outline" className="text-xs font-normal capitalize">
              {signal.regime} regime
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-4">
          {(() => {
            const isStrong =
              signal.signal === 'STRONG_BUY' || signal.signal === 'STRONG_SELL'
            return (
              <span className="relative inline-flex rounded-md">
                {isStrong && (
                  <span
                    className="absolute inset-0 rounded-md animate-ping opacity-30 bg-current"
                    aria-hidden
                  />
                )}
                <Badge
                  className={cn(
                    'relative px-4 py-2 text-base flex items-center gap-1.5',
                    getSignalBadgeClasses(signal.signal)
                  )}
                  aria-label={`Trading signal: ${signal.signal}`}
                >
                  {getSignalIcon(signal.signal)}
                  {signal.signal ? signal.signal.toString().replace('_', ' ') : 'Unknown'}
                </Badge>
              </span>
            )
          })()}
          <div className="flex-1">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-muted-foreground">Signal confidence</span>
              <span className="font-medium">{formatConfidence(overallConfidence)}</span>
            </div>
            <ConfidenceProgress value={overallConfidence} className="h-2" />
            {displayConfidence.source === 'reasoning' &&
              policyConfidencePercent != null &&
              Math.abs(policyConfidencePercent - overallConfidence) >= 2 && (
                <p className="text-[10px] text-muted-foreground mt-0.5 leading-tight tabular-nums">
                  Raw score: {formatConfidence(policyConfidencePercent)}
                </p>
              )}
          </div>
        </div>

        {/* v43 Signal Economics */}
        {(signal.expected_return != null ||
          signal.threshold != null ||
          Boolean(signal.v43_gate_reject)) && (
          <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground space-y-1">
            <p className="font-medium text-foreground">Signal economics</p>
            <ul className="list-inside list-disc space-y-0.5 tabular-nums">
              {signal.expected_return != null && Number.isFinite(Number(signal.expected_return)) && (
                <li>
                  Expected return:{' '}
                  <span className="text-foreground font-medium">
                    {Number(signal.expected_return).toFixed(5)}
                  </span>
                </li>
              )}
              {signal.threshold != null && Number.isFinite(Number(signal.threshold)) && (
                <li>
                  Threshold:{' '}
                  <span className="text-foreground">{Number(signal.threshold).toFixed(5)}</span>
                </li>
              )}
              {signal.v43_gate_reject != null && signal.v43_gate_reject !== '' && (
                <li>
                  Gate reject:{' '}
                  <span className="text-foreground">{String(signal.v43_gate_reject)}</span>
                </li>
              )}
            </ul>
          </div>
        )}

        {/* Agent introspection summary */}
        {signal.agent_introspection && (
          <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-[10px] text-muted-foreground space-y-0.5">
            <p className="font-medium text-foreground text-xs">Decision context</p>
            <p>
              {signal.agent_introspection.policy_mode} · score{' '}
              {signal.agent_introspection.trade_score ?? '—'} · memory{' '}
              {signal.agent_introspection.memory_context_count}
            </p>
          </div>
        )}

        {/* Latest reflection */}
        {(lastReflection ?? signal.reflection_snapshot) && (
          <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-[10px] text-muted-foreground space-y-0.5">
            <p className="font-medium text-foreground text-xs">Latest reflection</p>
            <p>
              quality{' '}
              {formatConfidence(
                (lastReflection ?? signal.reflection_snapshot)!.quality_score <= 1
                  ? (lastReflection ?? signal.reflection_snapshot)!.quality_score * 100
                  : (lastReflection ?? signal.reflection_snapshot)!.quality_score
              )}{' '}
              · {(lastReflection ?? signal.reflection_snapshot)!.calibration_bucket}
            </p>
          </div>
        )}

        {signal.agent_decision_reasoning && (
          <div className="pt-2 border-t">
            <p className="text-sm font-medium mb-1">Decision Reasoning</p>
            <p className="text-xs text-muted-foreground">{signal.agent_decision_reasoning}</p>
          </div>
        )}

        {signal.timestamp && (
          <DataFreshnessIndicator timestamp={signal.timestamp} />
        )}
      </CardContent>
    </Card>
  )
}
