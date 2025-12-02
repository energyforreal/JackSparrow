'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { ConfidenceProgress } from './ConfidenceProgress'
import { Badge } from '@/components/ui/badge'
import { ReasoningChain, ReasoningStep } from '@/types'
import { normalizeConfidenceToPercent, formatConfidence } from '@/utils/formatters'

interface ReasoningChainViewProps {
  // Array of reasoning steps as sent over WebSocket.
  reasoningChain?: ReasoningStep[]
  // Optional full chain metadata (typically from HTTP /predict).
  chainMeta?: ReasoningChain
  overallConfidence?: number
}

export function ReasoningChainView({
  reasoningChain,
  chainMeta,
  overallConfidence,
}: ReasoningChainViewProps) {
  if (!reasoningChain || reasoningChain.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Agent Reasoning Chain</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No reasoning chain available yet. Trigger a prediction to see the agent&apos;s
            6-step reasoning process from situational assessment through confidence
            calibration.
          </p>
        </CardContent>
      </Card>
    )
  }

  const sortedSteps = [...reasoningChain].sort(
    (a, b) => a.step_number - b.step_number
  )

  const finalConfidencePercent =
    chainMeta?.final_confidence !== undefined
      ? normalizeConfidenceToPercent(chainMeta.final_confidence)
      : normalizeConfidenceToPercent(overallConfidence ?? 0)

  const stepConfidences = sortedSteps.map((step) =>
    normalizeConfidenceToPercent(step.confidence)
  )
  const averageStepConfidence =
    stepConfidences.length > 0
      ? stepConfidences.reduce((sum, c) => sum + c, 0) / stepConfidences.length
      : 0

  // Simple consistency metric based on variance of step confidences.
  let consistencyScore = 0
  if (stepConfidences.length <= 1) {
    consistencyScore = 100
  } else {
    const mean = averageStepConfidence
    const variance =
      stepConfidences.reduce((sum, c) => sum + (c - mean) ** 2, 0) /
      stepConfidences.length
    const stdDev = Math.sqrt(variance)
    // Map stdDev (0–50+) to a 0–100 score where lower deviation = higher consistency.
    const normalized = Math.max(0, Math.min(1, 1 - stdDev / 50))
    consistencyScore = normalized * 100
  }

  const STEP_TITLES: Record<number, string> = {
    1: 'Situational Assessment',
    2: 'Historical Context Retrieval',
    3: 'Model Consensus Analysis',
    4: 'Risk Assessment',
    5: 'Decision Synthesis',
    6: 'Confidence Calibration',
  }

  const STEP_SUMMARIES: Record<number, string> = {
    1: 'Understands current market regime, volatility, and any anomalies.',
    2: 'Finds similar past situations and learns from their outcomes.',
    3: 'Aggregates predictions from all active ML models into a consensus.',
    4: 'Evaluates portfolio heat, drawdown, volatility and other risk factors.',
    5: 'Combines signals, history and risk into a concrete trading decision.',
    6: 'Adjusts confidence based on historical calibration for this regime.',
  }

  const conclusionText =
    chainMeta?.conclusion ??
    sortedSteps[sortedSteps.length - 1]?.description ??
    'No conclusion available.'

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Agent Reasoning Chain</CardTitle>
          <div className="flex items-center gap-3">
            {finalConfidencePercent > 0 && (
              <Badge variant="outline" className="text-sm">
                Confidence: {formatConfidence(finalConfidencePercent)}
              </Badge>
            )}
          </div>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          Structured 6-step reasoning from situational assessment to calibrated confidence,
          using market context, historical memories, model consensus, and risk analysis.
        </p>
      </CardHeader>
      <CardContent>
        <Accordion type="single" collapsible className="w-full" aria-label="Reasoning steps">
          {sortedSteps.map((step) => {
            const stepConfidence = normalizeConfidenceToPercent(step.confidence)
            const title = STEP_TITLES[step.step_number] ?? step.step_name
            const summary =
              STEP_SUMMARIES[step.step_number] ??
              'Detailed reasoning for this step is shown below.'

            return (
              <AccordionItem
                key={step.step_number}
                value={`step-${step.step_number}`}
              >
                <AccordionTrigger>
                  <div className="flex items-center justify-between w-full pr-4">
                    <div className="flex flex-col items-start gap-1 text-left">
                      <span className="text-sm font-medium">
                        Step {step.step_number}: {title}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {summary}
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">
                        {formatConfidence(stepConfidence)}
                      </span>
                      <ConfidenceProgress value={stepConfidence} className="w-20 h-2" />
                    </div>
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-3 pt-2">
                    <div className="max-h-96 overflow-y-auto pr-2">
                      <p className="text-sm text-muted-foreground whitespace-pre-wrap break-words">
                        {step.description}
                      </p>
                    </div>
                    {step.evidence && step.evidence.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {step.evidence.map((evidence, index) => (
                          <Badge
                            key={index}
                            variant="outline"
                            className="text-[0.65rem]"
                          >
                            {evidence}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                </AccordionContent>
              </AccordionItem>
            )
          })}
        </Accordion>

        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          <Card className="bg-background/40 border-border/60">
            <CardContent className="py-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  Average step confidence
                </span>
                <span className="text-sm font-medium">
                  {formatConfidence(averageStepConfidence)}
                </span>
              </div>
            </CardContent>
          </Card>
          <Card className="bg-background/40 border-border/60">
            <CardContent className="py-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  Consistency score
                </span>
                <span className="text-sm font-medium">
                  {formatConfidence(consistencyScore)}
                </span>
              </div>
            </CardContent>
          </Card>
        </div>

        <Card className="mt-4 bg-accent/50 border-accent">
          <CardHeader className="py-3">
            <CardTitle className="text-sm font-semibold">
              Conclusion
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-h-64 overflow-y-auto pr-2">
              <p className="text-sm text-foreground whitespace-pre-wrap break-words">
                {conclusionText}
              </p>
            </div>
          </CardContent>
        </Card>
      </CardContent>
    </Card>
  )
}

        {/* Old layout retained for reference in git history
            (replaced by the richer 6-step UX above). */}
          {/* {overallConfidence !== undefined && (
            <Badge variant="outline" className="text-sm">
              Confidence: {overallConfidence}%
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <Accordion type="single" collapsible className="w-full">
          {sortedSteps.slice(0, -1).map((step) => (
            <AccordionItem key={step.step_number} value={`step-${step.step_number}`}>
              <AccordionTrigger>
                <div className="flex items-center justify-between w-full pr-4">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium">
                      Step {step.step_number}: {step.title}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      {step.confidence}%
                    </span>
                    <Progress value={step.confidence} className="w-16 h-2" />
                  </div>
                </div>
              </AccordionTrigger>
              <AccordionContent>
                <div className="space-y-3 pt-2">
                  <p className="text-sm text-muted-foreground">{step.content}</p>
                  {step.evidence && step.evidence.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {step.evidence.map((evidence, index) => (
                        <Badge key={index} variant="outline" className="text-xs">
                          {evidence}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
*/}
