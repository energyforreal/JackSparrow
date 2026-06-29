'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { ModelConsensusSnapshot } from '@/hooks/useTradingData'
import { Signal, ReflectionSnapshot } from '@/types'
import type { SignalType } from '@/types'
import { normalizeSignalType } from '@/types/enums'
import { normalizeConfidenceToPercent } from '@/utils/formatters'
import { cn } from '@/lib/utils'
import { formatConfidence } from '@/utils/formatters'
import { SignalEntryMetricsBlock } from './SignalEntryMetrics'
import { resolveDecisionReasoning, resolveHeroMetrics } from '@/utils/signalConfidence'
import { ConfidenceProgress } from './ConfidenceProgress'
import { DataFreshnessIndicator } from './DataFreshnessIndicator'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

interface SignalIndicatorProps {
  signal?: Signal
  lastReflection?: ReflectionSnapshot | null
  /** Live ensemble confidence from the model WebSocket channel. */
  modelConsensus?: ModelConsensusSnapshot | null
  /** @deprecated Use modelConsensus */
  modelEdge?: ModelConsensusSnapshot | null
}

const getSignalBadgeClasses = (signal: SignalType) => {
  switch (signal) {
    case 'STRONG_LONG':
      return 'bg-emerald-700 text-white hover:bg-emerald-800'
    case 'LONG':
      return 'bg-success text-white hover:bg-success/90'
    case 'HOLD':
      return 'bg-muted text-muted-foreground'
    case 'SHORT':
      return 'bg-error text-white hover:bg-error/90'
    case 'STRONG_SHORT':
      return 'bg-red-800 text-white hover:bg-red-900'
    default:
      return ''
  }
}

const getSignalIcon = (signal: SignalType) => {
  switch (signal) {
    case 'STRONG_LONG':
    case 'LONG':
      return <TrendingUp className="h-4 w-4" />
    case 'STRONG_SHORT':
    case 'SHORT':
      return <TrendingDown className="h-4 w-4" />
    default:
      return <Minus className="h-4 w-4" />
  }
}

function SignalEconomicsBlock({ signal }: { signal: Signal }) {
  const hasEconomics =
    signal.expected_return != null ||
    signal.threshold != null ||
    Boolean(signal.v43_gate_reject)
  if (!hasEconomics) return null

  return (
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
  )
}

export function SignalIndicator({
  signal,
  lastReflection,
  modelConsensus,
  modelEdge,
}: SignalIndicatorProps) {
  const consensus = modelConsensus ?? modelEdge

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

  const canonSignal = normalizeSignalType(signal.signal) ?? 'HOLD'
  const entryMetrics = resolveHeroMetrics(signal)

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>
            {signal.position_lifecycle === 'managing' || signal.position_lifecycle === 'exit_ready'
              ? 'Position Lifecycle'
              : 'Trading Signal'}
          </CardTitle>
          {signal.position_lifecycle && (
            <Badge variant="secondary" className="text-xs capitalize">
              {signal.position_lifecycle.replace(/_/g, ' ')}
            </Badge>
          )}
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
              canonSignal === 'STRONG_LONG' || canonSignal === 'STRONG_SHORT'
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
                    getSignalBadgeClasses(canonSignal)
                  )}
                  aria-label={`Trading signal: ${canonSignal}`}
                >
                  {getSignalIcon(canonSignal)}
                  {canonSignal ? canonSignal.toString().replace('_', ' ') : 'Unknown'}
                </Badge>
              </span>
            )
          })()}
          <div className="flex-1 min-w-0">
            <SignalEntryMetricsBlock signal={signal} />
          </div>
        </div>

        <SignalEconomicsBlock signal={signal} />

        {entryMetrics?.entryMarginPercent != null && (
          <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
            <div className="flex justify-between text-xs mb-1">
              <span className="text-muted-foreground">Entry margin</span>
              <span className="font-medium tabular-nums">
                {formatConfidence(entryMetrics.entryMarginPercent)}
              </span>
            </div>
            <ConfidenceProgress value={entryMetrics.entryMarginPercent} className="h-1.5" />
          </div>
        )}

        {consensus && consensus.confidence > 0 && (
          <div className="rounded-md border border-dashed border-border/60 px-3 py-2">
            <div className="flex justify-between text-xs mb-1">
              <span className="text-muted-foreground">Model consensus</span>
              <span className="font-medium tabular-nums">
                {formatConfidence(normalizeConfidenceToPercent(consensus.confidence))}
                {consensus.signal ? ` · ${consensus.signal}` : ''}
              </span>
            </div>
            <ConfidenceProgress
              value={normalizeConfidenceToPercent(consensus.confidence)}
              className="h-1.5 opacity-80"
            />
            <p className="text-[10px] text-muted-foreground mt-1">
              Mean ensemble confidence from the model channel; not economic edge.
            </p>
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

        {(() => {
          const hypSnap = signal.hypothesis_snapshot
          const topHyps =
            hypSnap?.hypotheses?.slice(0, 3) ??
            signal.agent_introspection?.hypothesis_top ??
            []
          const aggregateDir =
            hypSnap?.aggregate_direction ??
            topHyps[0]?.direction ??
            undefined
          const env =
            hypSnap?.environment ?? signal.agent_introspection?.environment_scores
          if (!topHyps.length && !aggregateDir) return null
          return (
            <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-[10px] text-muted-foreground space-y-1">
              <p className="font-medium text-foreground text-xs">Hypotheses</p>
              {aggregateDir && (
                <p>
                  aggregate {aggregateDir}
                  {hypSnap?.aggregate_confidence != null
                    ? ` · conf ${formatConfidence(hypSnap.aggregate_confidence * 100)}`
                    : ''}
                  {hypSnap?.hypothesis_margin != null
                    ? ` · margin ${(hypSnap.hypothesis_margin * 100).toFixed(1)}%`
                    : ''}
                </p>
              )}
              {topHyps.length > 0 && (
                <ul className="space-y-0.5">
                  {topHyps.map((h) => (
                    <li key={h.id}>
                      {h.id} · {h.direction} ·{' '}
                      {formatConfidence(
                        (h.weighted_confidence ?? h.confidence) <= 1
                          ? (h.weighted_confidence ?? h.confidence) * 100
                          : (h.weighted_confidence ?? h.confidence)
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {env && Object.keys(env).length > 0 && (
                <p className="truncate">
                  env:{' '}
                  {Object.entries(env)
                    .slice(0, 4)
                    .map(([k, v]) => `${k} ${(v * 100).toFixed(0)}%`)
                    .join(' · ')}
                </p>
              )}
            </div>
          )
        })()}

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
