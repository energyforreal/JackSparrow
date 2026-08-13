'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { ConfidenceProgress } from './ConfidenceProgress'
import { ReasoningChain, ReasoningStep, TfStance } from '@/types'
import { normalizeConfidenceToPercent, formatConfidence, formatDateTime } from '@/utils/formatters'
import { LoadingSkeleton } from './LoadingSpinner'
import { CheckCircle2, Circle, AlertCircle } from 'lucide-react'

interface ReasoningChainViewProps {
  reasoningChain?: ReasoningStep[]
  chainMeta?: ReasoningChain
  overallConfidence?: number
  isLoading?: boolean
  // Kept for API compatibility but no longer rendered as ML model rows
  modelConsensus?: unknown[]
  individualModelReasoning?: unknown[]
  modelVersion?: string
  inferenceLatencyMs?: number
  inferenceMode?: string
  /** @deprecated use pathEdge */
  v43PathEdge?: number
  /** @deprecated use threshold */
  v43Threshold?: number
  /** @deprecated use gateReject */
  v43GateReject?: string
  pathEdge?: number
  threshold?: number
  gateReject?: string
  multiTfPredictions?: Record<string, TfStance>
  crossTfSummary?: Record<string, unknown>
  longEdge?: number
  shortEdge?: number
}

const TF_ORDER = ['tf_5m', 'tf_15m', 'tf_30m', 'tf_1h', 'tf_2h']

const stepStatusIcon = (confidence: number) => {
  const pct = normalizeConfidenceToPercent(confidence)
  if (pct >= 65) return <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
  if (pct >= 40) return <Circle className="h-4 w-4 text-amber-500 shrink-0" />
  return <AlertCircle className="h-4 w-4 text-red-500 shrink-0" />
}

function formatEdge(value: number | undefined | null): string {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return Number(value).toFixed(5)
}

function orderedStances(
  multiTf: Record<string, TfStance> | undefined
): Array<{ key: string; stance: TfStance }> {
  if (!multiTf) return []
  const keys = [
    ...TF_ORDER.filter((k) => k in multiTf),
    ...Object.keys(multiTf).filter((k) => !TF_ORDER.includes(k)),
  ]
  return keys.map((key) => ({ key, stance: multiTf[key] }))
}

export function ReasoningChainView({
  reasoningChain,
  chainMeta,
  overallConfidence,
  isLoading = false,
  v43PathEdge,
  v43Threshold,
  v43GateReject,
  pathEdge,
  threshold,
  gateReject,
  multiTfPredictions,
  crossTfSummary,
  longEdge,
  shortEdge,
}: ReasoningChainViewProps) {
  const resolvedPathEdge = pathEdge ?? v43PathEdge
  const resolvedThreshold = threshold ?? v43Threshold
  const resolvedGateReject = gateReject ?? v43GateReject
  const stances = orderedStances(multiTfPredictions)

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Signal Rationale</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map((stepNum) => (
              <div key={stepNum} className="border rounded-lg p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <LoadingSkeleton className="h-5 w-48" />
                  <LoadingSkeleton className="h-4 w-16" />
                </div>
                <LoadingSkeleton className="h-4 w-full" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    )
  }

  const hasSteps = reasoningChain && reasoningChain.length > 0
  const hasEconomics =
    resolvedPathEdge != null ||
    resolvedThreshold != null ||
    Boolean(resolvedGateReject) ||
    longEdge != null ||
    shortEdge != null

  if (!hasSteps && !hasEconomics && stances.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Signal Rationale</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No rationale available yet. Trigger a prediction to see multi-timeframe stances and
            path economics.
          </p>
        </CardContent>
      </Card>
    )
  }

  const sortedSteps = hasSteps
    ? [...reasoningChain!].sort((a, b) => a.step_number - b.step_number)
    : []

  const finalConfidencePercent =
    chainMeta?.final_confidence !== undefined
      ? normalizeConfidenceToPercent(chainMeta.final_confidence)
      : normalizeConfidenceToPercent(overallConfidence ?? 0)

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Signal Rationale</CardTitle>
          {finalConfidencePercent > 0 && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Final confidence</span>
              <span className="font-semibold tabular-nums">
                {formatConfidence(finalConfidencePercent)}
              </span>
            </div>
          )}
        </div>
        {chainMeta?.timestamp && (
          <p className="text-xs text-muted-foreground mt-1">
            {formatDateTime(chainMeta.timestamp)}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {stances.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm font-medium">Multi-timeframe stances</p>
            <div className="overflow-x-auto -mx-1">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground text-left border-b">
                    <th className="py-1.5 pr-2 font-medium">TF</th>
                    <th className="py-1.5 pr-2 font-medium">Signal</th>
                    <th className="py-1.5 pr-2 font-medium tabular-nums">Long</th>
                    <th className="py-1.5 pr-2 font-medium tabular-nums">Short</th>
                    <th className="py-1.5 pr-2 font-medium tabular-nums">Size</th>
                    <th className="py-1.5 font-medium tabular-nums">Conf</th>
                  </tr>
                </thead>
                <tbody>
                  {stances.map(({ key, stance }) => {
                    const label =
                      stance.resolution ||
                      stance.tf_key ||
                      key.replace(/^tf_/, '')
                    const conf =
                      stance.confidence != null
                        ? normalizeConfidenceToPercent(stance.confidence)
                        : null
                    return (
                      <tr key={key} className="border-b border-border/40 last:border-0">
                        <td className="py-1.5 pr-2 font-medium">{label}</td>
                        <td className="py-1.5 pr-2">
                          <Badge variant="outline" className="text-[10px] font-normal">
                            {stance.local_signal || '—'}
                          </Badge>
                        </td>
                        <td className="py-1.5 pr-2 tabular-nums">
                          {formatEdge(stance.long_edge ?? stance.path_edge)}
                        </td>
                        <td className="py-1.5 pr-2 tabular-nums">
                          {formatEdge(
                            stance.short_edge ??
                              (stance.path_edge != null ? -Number(stance.path_edge) : null)
                          )}
                        </td>
                        <td className="py-1.5 pr-2 tabular-nums">
                          {stance.size_scale != null && Number.isFinite(stance.size_scale)
                            ? `${(Number(stance.size_scale) * 100).toFixed(0)}%`
                            : '—'}
                        </td>
                        <td className="py-1.5 tabular-nums">
                          {conf != null ? formatConfidence(conf) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {crossTfSummary && Object.keys(crossTfSummary).length > 0 && (
              <p className="text-[10px] text-muted-foreground">
                Cross-TF:{' '}
                {Object.entries(crossTfSummary)
                  .slice(0, 4)
                  .map(([k, v]) => `${k}=${String(v)}`)
                  .join(' · ')}
              </p>
            )}
          </div>
        )}

        {hasEconomics && (
          <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground space-y-1">
            <p className="font-medium text-foreground">Path economics</p>
            <ul className="list-inside list-disc space-y-0.5 tabular-nums">
              {longEdge != null && Number.isFinite(longEdge) && (
                <li>
                  Long edge:{' '}
                  <span className="text-foreground font-medium">{longEdge.toFixed(5)}</span>
                </li>
              )}
              {shortEdge != null && Number.isFinite(shortEdge) && (
                <li>
                  Short edge:{' '}
                  <span className="text-foreground font-medium">{shortEdge.toFixed(5)}</span>
                </li>
              )}
              {resolvedPathEdge != null && Number.isFinite(resolvedPathEdge) && (
                <li>
                  Path edge:{' '}
                  <span className="text-foreground font-medium">
                    {resolvedPathEdge.toFixed(5)}
                  </span>
                </li>
              )}
              {resolvedThreshold != null && Number.isFinite(resolvedThreshold) && (
                <li>
                  Threshold:{' '}
                  <span className="text-foreground">{resolvedThreshold.toFixed(5)}</span>
                </li>
              )}
              {resolvedGateReject && resolvedGateReject !== '' && (
                <li>
                  Gate reject:{' '}
                  <span className="text-foreground">{resolvedGateReject}</span>
                </li>
              )}
            </ul>
          </div>
        )}

        {sortedSteps.length > 0 && (
          <Accordion type="single" collapsible defaultValue="">
            <AccordionItem value="steps">
              <AccordionTrigger className="text-sm font-medium">
                Reasoning detail ({sortedSteps.length})
              </AccordionTrigger>
              <AccordionContent>
                <div className="space-y-3 mt-2">
                  {sortedSteps.map((step) => {
                    const pct = normalizeConfidenceToPercent(step.confidence)
                    return (
                      <div key={step.step_number} className="border rounded-lg p-3 space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            {stepStatusIcon(step.confidence)}
                            <span className="text-sm font-medium">
                              {step.step_number}. {step.step_name}
                            </span>
                          </div>
                          <Badge variant="outline" className="text-xs tabular-nums shrink-0">
                            {formatConfidence(pct)}
                          </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground pl-6">{step.description}</p>
                        <div className="pl-6">
                          <ConfidenceProgress value={pct} className="h-1.5" />
                        </div>
                        {step.evidence && step.evidence.length > 0 && (
                          <ul className="pl-6 space-y-0.5">
                            {step.evidence.map((e, i) => (
                              <li key={i} className="text-[10px] text-muted-foreground">
                                • {e}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )
                  })}
                </div>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        )}

        {chainMeta?.conclusion && (
          <div className="rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
            <p className="font-medium text-foreground mb-1">Conclusion</p>
            <p>{chainMeta.conclusion}</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
