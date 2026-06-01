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
import { ReasoningChain, ReasoningStep } from '@/types'
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
  v43ExpectedReturn?: number
  v43Threshold?: number
  v43GateReject?: string
}

const stepStatusIcon = (confidence: number) => {
  const pct = normalizeConfidenceToPercent(confidence)
  if (pct >= 65) return <CheckCircle2 className="h-4 w-4 text-emerald-500 shrink-0" />
  if (pct >= 40) return <Circle className="h-4 w-4 text-amber-500 shrink-0" />
  return <AlertCircle className="h-4 w-4 text-red-500 shrink-0" />
}

export function ReasoningChainView({
  reasoningChain,
  chainMeta,
  overallConfidence,
  isLoading = false,
  v43ExpectedReturn,
  v43Threshold,
  v43GateReject,
}: ReasoningChainViewProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Signal Rationale</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-3">
            {[1, 2, 3, 4, 5, 6].map((stepNum) => (
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

  if (!hasSteps && !v43ExpectedReturn && !v43GateReject) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Signal Rationale</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No rationale available yet. Trigger a prediction to see the agent&apos;s step-by-step
            reasoning from market assessment through confidence calibration.
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
        {/* v43 economics summary */}
        {(v43ExpectedReturn != null || v43Threshold != null || v43GateReject) && (
          <div className="rounded-md border border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground space-y-1">
            <p className="font-medium text-foreground">Decision economics</p>
            <ul className="list-inside list-disc space-y-0.5 tabular-nums">
              {v43ExpectedReturn != null && Number.isFinite(v43ExpectedReturn) && (
                <li>
                  Expected return:{' '}
                  <span className="text-foreground font-medium">
                    {v43ExpectedReturn.toFixed(5)}
                  </span>
                </li>
              )}
              {v43Threshold != null && Number.isFinite(v43Threshold) && (
                <li>
                  Threshold:{' '}
                  <span className="text-foreground">{v43Threshold.toFixed(5)}</span>
                </li>
              )}
              {v43GateReject && v43GateReject !== '' && (
                <li>
                  Gate reject:{' '}
                  <span className="text-foreground">{v43GateReject}</span>
                </li>
              )}
            </ul>
          </div>
        )}

        {/* Reasoning steps */}
        {sortedSteps.length > 0 && (
          <Accordion type="single" collapsible defaultValue="steps">
            <AccordionItem value="steps">
              <AccordionTrigger className="text-sm font-medium">
                Reasoning steps ({sortedSteps.length})
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

        {/* Chain conclusion */}
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
