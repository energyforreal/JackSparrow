'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Signal, SignalType, ReflectionSnapshot } from '@/types'
import type { ModelEdgeSnapshot } from '@/hooks/useTradingData'
import { normalizeConfidenceToPercent } from '@/utils/formatters'
import { cn } from '@/lib/utils'
import { formatConfidence } from '@/utils/formatters'
import { SignalEntryMetricsBlock } from './SignalEntryMetrics'
import { resolveDecisionReasoning } from '@/utils/signalConfidence'
import { ConfidenceProgress } from './ConfidenceProgress'
import { DataFreshnessIndicator } from './DataFreshnessIndicator'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface SignalIndicatorProps {
  signal?: Signal
  lastReflection?: ReflectionSnapshot | null
  modelEdge?: ModelEdgeSnapshot | null
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

export function SignalIndicator({ signal, lastReflection, modelEdge }: SignalIndicatorProps) {
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
          <div className="flex-1 min-w-0">
            <SignalEntryMetricsBlock signal={signal} />
          </div>
        </div>

        {modelEdge && modelEdge.confidence > 0 && (
          <div className="rounded-md border border-dashed border-border/60 px-3 py-2">
            <div className="flex justify-between text-xs mb-1">
              <span className="text-muted-foreground">Model edge</span>
              <span className="font-medium tabular-nums">
                {formatConfidence(normalizeConfidenceToPercent(modelEdge.confidence))}
                {modelEdge.signal ? ` · ${modelEdge.signal}` : ''}
              </span>
            </div>
            <ConfidenceProgress
              value={normalizeConfidenceToPercent(modelEdge.confidence)}
              className="h-1.5 opacity-80"
            />
          </div>
        )}

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

        {signal.agent_introspection && (
          <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-[10px] text-muted-foreground space-y-0.5">
            <p className="font-medium text-foreground text-xs">Agent context</p>
            <p>
              {signal.agent_introspection.policy_mode} · thesis{' '}
              {signal.thesis_signal ?? signal.agent_introspection.thesis_signal ?? '—'} ·
              memory {signal.agent_introspection.memory_context_count}
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

        {(() => {
          const reasoning = resolveDecisionReasoning(signal)
          if (!reasoning) return null
          return (
            <div className="pt-2 border-t">
              <p className="text-sm font-medium mb-1">Decision Reasoning</p>
              <p className="text-xs text-muted-foreground">{reasoning}</p>
            </div>
          )
        })()}

        {(signal.timestamp || signal.server_timestamp_ms) && (
          <DataFreshnessIndicator
            timestamp={signal.timestamp}
            serverTimestampMs={signal.server_timestamp_ms}
          />
        )}
      </CardContent>
    </Card>
  )
}
