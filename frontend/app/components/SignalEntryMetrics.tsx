'use client'

import { ConfidenceProgress } from './ConfidenceProgress'
import { Badge } from '@/components/ui/badge'
import type { Signal } from '@/types'
import { formatConfidence } from '@/utils/formatters'
import {
  isHoldNonActionableDisplay,
  resolveDisplayConfidence,
  resolveSignalEntryMetrics,
} from '@/utils/signalConfidence'
import { cn } from '@/lib/utils'

interface SignalEntryMetricsProps {
  signal: Signal
  /** Compact layout for Trading Decision flow card */
  compact?: boolean
}

export function SignalEntryMetricsBlock({
  signal,
  compact = false,
}: SignalEntryMetricsProps) {
  const display = resolveDisplayConfidence(signal)
  const metrics = resolveSignalEntryMetrics(signal)
  if (!metrics) return null

  const holdDim = isHoldNonActionableDisplay(signal)

  const reasoningLabel =
    display.source === 'reasoning' ? 'Reasoning confidence' : 'Signal confidence'
  const policyLabel = 'Policy entry confidence'

  if (compact) {
    return (
      <div className="space-y-1 text-xs text-muted-foreground">
        <p>
          <span className="font-medium text-foreground">{reasoningLabel}:</span>{' '}
          {formatConfidence(metrics.reasoningPercent)}
        </p>
        {metrics.showSplitConfidence && (
          <p>
            <span className="font-medium text-foreground">{policyLabel}:</span>{' '}
            {formatConfidence(metrics.policyEntryPercent)}
            <span className="ml-1 opacity-80">(used for entry gating)</span>
          </p>
        )}
        {metrics.tradeScore != null && (
          <p className="tabular-nums">
            <span className="font-medium text-foreground">Trade score:</span>{' '}
            {Math.round(metrics.tradeScore.score)}
            {metrics.tradeScore.passed != null && (
              <Badge
                variant={metrics.tradeScore.passed ? 'default' : 'secondary'}
                className="ml-1.5 text-[10px] px-1.5 py-0"
              >
                {metrics.tradeScore.passed ? 'pass' : 'below min'}
              </Badge>
            )}
          </p>
        )}
        {metrics.signalStrengthPercent != null && (
          <p>
            Signal strength: {formatConfidence(metrics.signalStrengthPercent)}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className={cn('space-y-3', holdDim && 'opacity-50')}>
      {holdDim && (
        <p className="text-[10px] text-muted-foreground">HOLD — confidence bars cleared (no entry).</p>
      )}
      <div>
        <div className="flex justify-between text-sm mb-1">
          <span className="text-muted-foreground">{reasoningLabel}</span>
          <span className="font-medium tabular-nums">
            {formatConfidence(metrics.reasoningPercent)}
          </span>
        </div>
        <ConfidenceProgress value={metrics.reasoningPercent} className="h-2" />
        <p className="text-[10px] text-muted-foreground mt-0.5 leading-tight">
          Calibrated across reasoning steps (may differ from execution gates).
        </p>
      </div>

      <div
        className={cn(
          'rounded-md border px-3 py-2',
          metrics.showSplitConfidence
            ? 'border-primary/30 bg-primary/5'
            : 'border-border/60 bg-muted/20'
        )}
      >
        <div className="flex justify-between text-sm mb-1">
          <span className="text-muted-foreground font-medium">{policyLabel}</span>
          <span className="font-medium tabular-nums">
            {formatConfidence(metrics.policyEntryPercent)}
          </span>
        </div>
        <ConfidenceProgress
          value={metrics.policyEntryPercent}
          className="h-1.5 opacity-90"
        />
        <p className="text-[10px] text-muted-foreground mt-1 leading-tight">
          Agent policy / ML candidate — authoritative for DecisionReady and risk
          approval.
        </p>
        {metrics.tradeScore != null && (
          <div className="flex flex-wrap items-center gap-2 mt-2 pt-2 border-t border-border/50 text-xs">
            <span className="text-muted-foreground">Trade score</span>
            <span className="font-semibold text-foreground tabular-nums text-sm">
              {Math.round(metrics.tradeScore.score)}
              <span className="text-muted-foreground font-normal"> / 100</span>
            </span>
            {metrics.tradeScore.passed != null && (
              <Badge
                variant={metrics.tradeScore.passed ? 'default' : 'secondary'}
                className="text-[10px]"
              >
                {metrics.tradeScore.passed ? 'passed' : 'not passed'}
              </Badge>
            )}
            <span className="text-[10px] text-muted-foreground w-full">
              Confluence gate (thesis + v43 gates + structure); primary adoption
              signal besides policy %.
            </span>
          </div>
        )}
      </div>

      {metrics.signalStrengthPercent != null && (
        <p className="text-[10px] text-muted-foreground tabular-nums">
          Entry margin strength: {formatConfidence(metrics.signalStrengthPercent)}
        </p>
      )}
    </div>
  )
}
