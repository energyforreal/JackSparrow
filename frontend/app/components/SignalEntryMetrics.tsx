'use client'

import { ConfidenceProgress } from './ConfidenceProgress'
import { Badge } from '@/components/ui/badge'
import type { Signal } from '@/types'
import { formatConfidence } from '@/utils/formatters'
import {
  resolveHeroMetrics,
  resolveSignalEntryMetrics,
} from '@/utils/signalConfidence'
import { cn } from '@/lib/utils'

interface SignalEntryMetricsProps {
  signal: Signal
  /** Compact layout for Trading Decision flow card */
  compact?: boolean
}

const TRADE_SCORE_COMPONENT_LABELS: Record<string, string> = {
  thesis: 'Thesis',
  ml: 'ML',
  regime_fit: 'Regime',
  liquidity: 'Liquidity',
  structure: 'Structure',
  gates: 'Gates',
  multi_horizon: 'Horizon',
}

export function SignalEntryMetricsBlock({
  signal,
  compact = false,
}: SignalEntryMetricsProps) {
  const hero = resolveHeroMetrics(signal)
  const metrics = resolveSignalEntryMetrics(signal)
  if (!hero || !metrics) return null

  const { holdDim } = hero

  if (compact) {
    return (
      <div
        className={cn('space-y-1 text-xs text-muted-foreground', holdDim && 'opacity-60')}
      >
        {holdDim && (
          <p className="text-[10px] font-medium text-foreground">HOLD — no entry</p>
        )}
        <p>
          <span className="font-medium text-foreground">Policy entry:</span>{' '}
          {formatConfidence(hero.policyEntryPercent)}
        </p>
        {hero.economicEdge != null && (
          <p className="tabular-nums">
            <span className="font-medium text-foreground">Economic edge:</span>{' '}
            {hero.economicEdge >= 0 ? '+' : ''}
            {hero.economicEdge.toFixed(5)}
          </p>
        )}
        {hero.entryMarginPercent != null && (
          <p>
            Entry margin: {formatConfidence(hero.entryMarginPercent)}
          </p>
        )}
        {hero.tradeScore != null && (
          <p className="tabular-nums">
            Trade score: {Math.round(hero.tradeScore.score)}
            {hero.tradeScore.passed != null && (
              <Badge
                variant={hero.tradeScore.passed ? 'default' : 'secondary'}
                className="ml-1.5 text-[10px] px-1.5 py-0"
              >
                {hero.tradeScore.passed ? 'pass' : 'below min'}
              </Badge>
            )}
          </p>
        )}
        {hero.reasoningPercent != null && (
          <p className="opacity-80">
            Reasoning: {formatConfidence(hero.reasoningPercent)}
            {hero.reasoningRawPercent != null &&
              Math.abs(hero.reasoningRawPercent - hero.reasoningPercent) >= 2 && (
                <span className="ml-1">
                  (raw {formatConfidence(hero.reasoningRawPercent)})
                </span>
              )}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className={cn('space-y-3', holdDim && 'opacity-60')}>
      {holdDim && (
        <p className="text-[10px] font-medium text-foreground">
          HOLD — no entry (values shown for diagnostics).
        </p>
      )}

      <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2">
        <div className="flex justify-between text-sm mb-1">
          <span className="text-muted-foreground font-medium">Policy entry confidence</span>
          <span className="font-medium tabular-nums">
            {formatConfidence(hero.policyEntryPercent)}
          </span>
        </div>
        <ConfidenceProgress value={hero.policyEntryPercent} className="h-2" />
        <p className="text-[10px] text-muted-foreground mt-1 leading-tight">
          Authoritative for DecisionReady and risk approval.
        </p>
      </div>

      {hero.economicEdge != null && (
        <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
          <div className="flex justify-between text-sm mb-1">
            <span className="text-muted-foreground">Economic edge</span>
            <span className="font-medium tabular-nums">
              {hero.economicEdge >= 0 ? '+' : ''}
              {hero.economicEdge.toFixed(5)}
            </span>
          </div>
          {hero.economicEdgeBarPercent != null && (
            <ConfidenceProgress value={hero.economicEdgeBarPercent} className="h-1.5" />
          )}
          <p className="text-[10px] text-muted-foreground mt-1">
            Expected return minus threshold (signed).
          </p>
        </div>
      )}

      {hero.entryMarginPercent != null && (
        <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
          <div className="flex justify-between text-sm mb-1">
            <span className="text-muted-foreground">Entry margin</span>
            <span className="font-medium tabular-nums">
              {formatConfidence(hero.entryMarginPercent)}
            </span>
          </div>
          <ConfidenceProgress value={hero.entryMarginPercent} className="h-1.5" />
          <p className="text-[10px] text-muted-foreground mt-1">
            Buy vs sell probability separation.
          </p>
        </div>
      )}

      {hero.tradeScore != null && (
        <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2">
          <div className="flex flex-wrap items-center gap-2 text-xs mb-2">
            <span className="text-muted-foreground font-medium">Trade score</span>
            <span className="font-semibold text-foreground tabular-nums text-sm">
              {Math.round(hero.tradeScore.score)}
              <span className="text-muted-foreground font-normal"> / 100</span>
            </span>
            {hero.tradeScore.passed != null && (
              <Badge
                variant={hero.tradeScore.passed ? 'default' : 'secondary'}
                className="text-[10px]"
              >
                {hero.tradeScore.passed ? 'passed' : 'not passed'}
              </Badge>
            )}
          </div>
          {hero.tradeScore.components &&
            Object.keys(hero.tradeScore.components).length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(hero.tradeScore.components).map(([key, val]) => (
                  <Badge key={key} variant="outline" className="text-[10px] tabular-nums">
                    {TRADE_SCORE_COMPONENT_LABELS[key] ?? key}: {Math.round(val)}
                  </Badge>
                ))}
              </div>
            )}
        </div>
      )}

      {hero.reasoningPercent != null && (
        <div className="text-[10px] text-muted-foreground space-y-0.5 border-t border-border/40 pt-2">
          <p>
            Reasoning confidence:{' '}
            <span className="text-foreground font-medium tabular-nums">
              {formatConfidence(hero.reasoningPercent)}
            </span>
            {hero.reasoningRawPercent != null &&
              Math.abs(hero.reasoningRawPercent - hero.reasoningPercent) >= 2 && (
                <span className="ml-1">
                  (raw {formatConfidence(hero.reasoningRawPercent)})
                </span>
              )}
          </p>
          {!metrics.showSplitConfidence &&
            hero.policyReasoningDelta != null &&
            Math.abs(hero.policyReasoningDelta) < 1 && (
              <p>Policy matches reasoning (±{Math.abs(hero.policyReasoningDelta).toFixed(1)}%).</p>
            )}
        </div>
      )}
    </div>
  )
}
