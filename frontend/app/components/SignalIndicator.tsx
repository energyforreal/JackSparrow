'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Signal, SignalType, ReflectionSnapshot } from '@/types'
import type { ModelEdgeSnapshot } from '@/hooks/useTradingData'
import { normalizeConfidenceToPercent } from '@/utils/formatters'
import { cn } from '@/lib/utils'
import { formatConfidence } from '@/utils/formatters'
import { SignalEntryMetricsBlock } from './SignalEntryMetrics'
import {
  isTransformerMtfPath,
  resolveConfidenceBand,
  resolveDecisionReasoning,
  resolveReasonCodes,
} from '@/utils/signalConfidence'
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

const bandBadgeVariant = (band: string) => {
  if (band === 'full') return 'default' as const
  if (band === 'reduced') return 'secondary' as const
  return 'outline' as const
}

function formatEdge(value: number | undefined | null): string | null {
  if (value == null || !Number.isFinite(Number(value))) return null
  return Number(value).toFixed(5)
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

  const band = resolveConfidenceBand(signal)
  const reasonCodes = resolveReasonCodes(signal)
  const transformerPath = isTransformerMtfPath(signal)
  const plan = signal.execution_plan
  const longEdge = formatEdge(signal.long_edge ?? plan?.long_edge)
  const shortEdge = formatEdge(signal.short_edge ?? plan?.short_edge)
  const winningEdge = formatEdge(signal.winning_edge ?? plan?.winning_edge)
  const threshold = formatEdge(signal.threshold ?? plan?.threshold)
  const pathEdge = formatEdge(signal.path_edge)
  const hasEconomics =
    longEdge != null ||
    shortEdge != null ||
    winningEdge != null ||
    threshold != null ||
    pathEdge != null ||
    Boolean(signal.v43_gate_reject)
  const showThesis =
    !transformerPath &&
    Boolean(signal.thesis_signal ?? signal.agent_introspection?.thesis_signal)

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Trading Signal</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            {(signal.regime || signal.transformer_vol_regime) && (
              <Badge variant="outline" className="text-xs font-normal capitalize">
                {signal.regime || signal.transformer_vol_regime} regime
              </Badge>
            )}
            {signal.primary_tf && (
              <Badge variant="outline" className="text-xs font-normal">
                {signal.primary_tf.replace(/^tf_/, '')}
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
          <div className="flex flex-wrap items-center gap-3">
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
            <Badge variant={bandBadgeVariant(band.band)} className="text-xs font-normal">
              {band.label}
            </Badge>
            {band.rrSoftAction && (
              <Badge variant="outline" className="text-xs font-normal">
                R:R {band.rrSoftAction.replace(/_/g, ' ')}
              </Badge>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <SignalEntryMetricsBlock signal={signal} />
          </div>
        </div>

        {(band.sizeScale != null || band.sizeFraction != null) && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-xs">
            {band.sizeScale != null && (
              <div>
                <p className="text-muted-foreground">Size scale</p>
                <p className="font-medium tabular-nums text-foreground">
                  {(band.sizeScale * 100).toFixed(0)}%
                </p>
              </div>
            )}
            {band.sizeFraction != null && (
              <div>
                <p className="text-muted-foreground">Size fraction</p>
                <p className="font-medium tabular-nums text-foreground">
                  {(band.sizeFraction * 100).toFixed(1)}%
                </p>
              </div>
            )}
            {plan?.stop_loss_pct != null && Number.isFinite(plan.stop_loss_pct) && (
              <div>
                <p className="text-muted-foreground">Stop %</p>
                <p className="font-medium tabular-nums text-foreground">
                  {(Number(plan.stop_loss_pct) * 100).toFixed(2)}%
                </p>
              </div>
            )}
            {plan?.take_profit_pct != null && Number.isFinite(plan.take_profit_pct) && (
              <div>
                <p className="text-muted-foreground">Take %</p>
                <p className="font-medium tabular-nums text-foreground">
                  {(Number(plan.take_profit_pct) * 100).toFixed(2)}%
                </p>
              </div>
            )}
          </div>
        )}

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

        {hasEconomics && (
          <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground space-y-1">
            <p className="font-medium text-foreground">Path economics</p>
            <ul className="list-inside list-disc space-y-0.5 tabular-nums">
              {longEdge != null && (
                <li>
                  Long edge:{' '}
                  <span className="text-foreground font-medium">{longEdge}</span>
                </li>
              )}
              {shortEdge != null && (
                <li>
                  Short edge:{' '}
                  <span className="text-foreground font-medium">{shortEdge}</span>
                </li>
              )}
              {winningEdge != null && (
                <li>
                  Winning edge:{' '}
                  <span className="text-foreground font-medium">{winningEdge}</span>
                </li>
              )}
              {longEdge == null && shortEdge == null && pathEdge != null && (
                <li>
                  Path edge:{' '}
                  <span className="text-foreground font-medium">{pathEdge}</span>
                </li>
              )}
              {threshold != null && (
                <li>
                  Threshold: <span className="text-foreground">{threshold}</span>
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

        {reasonCodes.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {reasonCodes.map((code) => (
              <Badge key={code} variant="outline" className="text-[10px] font-normal">
                {code}
              </Badge>
            ))}
          </div>
        )}

        {signal.agent_introspection && (
          <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-[10px] text-muted-foreground space-y-0.5">
            <p className="font-medium text-foreground text-xs">Agent context</p>
            <p>
              {signal.agent_introspection.policy_mode}
              {showThesis && (
                <>
                  {' '}
                  · thesis{' '}
                  {signal.thesis_signal ?? signal.agent_introspection.thesis_signal}
                </>
              )}
              {' '}
              · memory {signal.agent_introspection.memory_context_count}
            </p>
          </div>
        )}

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
