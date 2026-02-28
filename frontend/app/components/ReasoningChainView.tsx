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
import {
  ModelConsensus,
  ModelReasoning,
  ReasoningChain,
  ReasoningStep,
} from '@/types'
import {
  normalizeConfidenceToPercent,
  formatConfidence,
  getDataFreshnessColor,
  formatDateTime,
} from '@/utils/formatters'
import { LoadingSkeleton } from './LoadingSpinner'
import { ModelReasoningView } from './ModelReasoningView'

interface ReasoningChainViewProps {
  // Array of reasoning steps as sent over WebSocket.
  reasoningChain?: ReasoningStep[]
  // Optional full chain metadata (typically from HTTP /predict).
  chainMeta?: ReasoningChain
  overallConfidence?: number
  // Loading state for reasoning chain generation
  isLoading?: boolean
  // Model reasoning data for integration
  modelConsensus?: ModelConsensus[]
  individualModelReasoning?: ModelReasoning[]
}

export function ReasoningChainView({
  reasoningChain,
  chainMeta,
  overallConfidence,
  isLoading = false,
  modelConsensus,
  individualModelReasoning,
}: ReasoningChainViewProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Agent Reasoning Chain</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-2">
            <LoadingSkeleton className="h-4 w-32" />
            <LoadingSkeleton className="h-4 w-24" />
          </div>
          <div className="space-y-3">
            {[1, 2, 3, 4, 5, 6].map((stepNum) => (
              <div key={stepNum} className="border rounded-lg p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <LoadingSkeleton className="h-5 w-48" />
                  <LoadingSkeleton className="h-4 w-16" />
                </div>
                <LoadingSkeleton className="h-4 w-full" />
                <LoadingSkeleton className="h-4 w-3/4" />
              </div>
            ))}
          </div>
          <div className="flex justify-center">
            <LoadingSkeleton className="h-8 w-48" />
          </div>
        </CardContent>
      </Card>
    )
  }

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

  // Generate confidence tooltip text for each step
  const getConfidenceTooltip = (step: ReasoningStep): string => {
    const confidencePercent = normalizeConfidenceToPercent(step.confidence)

    switch (step.step_number) {
      case 1:
        return `Situational Assessment confidence (${confidencePercent.toFixed(1)}%) based on market data quality and feature completeness. Higher scores indicate better data reliability.`
      case 2:
        return `Historical Context confidence (${confidencePercent.toFixed(1)}%) based on similarity to past market situations. Higher scores indicate stronger historical precedents.`
      case 3:
        return `Model Consensus confidence (${confidencePercent.toFixed(1)}%) represents average confidence across all ML models. Higher scores indicate more reliable predictions.`
      case 4:
        return `Risk Assessment confidence (${confidencePercent.toFixed(1)}%) based on completeness of risk data (volatility, portfolio, metrics). Higher scores indicate more comprehensive risk evaluation.`
      case 5:
        return `Decision Synthesis confidence (${confidencePercent.toFixed(1)}%) based on model prediction strength and consistency. Higher scores indicate clearer trading signals.`
      case 6:
        return `Confidence Calibration (${confidencePercent.toFixed(1)}%) is the final calibrated confidence after considering step consistency and historical performance.`
      default:
        return `Step confidence: ${confidencePercent.toFixed(1)}%`
    }
  }

  // Generate dynamic summaries based on actual step data
  const generateStepSummary = (step: ReasoningStep): string => {
    const baseSummaries: Record<number, string> = {
      1: 'Analyzes current market conditions and data quality.',
      2: 'Searches for similar historical market situations.',
      3: 'Aggregates predictions from multiple ML models.',
      4: 'Assesses trading risks and portfolio exposure.',
      5: 'Synthesizes all inputs into a trading decision.',
      6: 'Calibrates final confidence based on step consistency.',
    }

    let summary = baseSummaries[step.step_number] || 'Processing step analysis.'

    // Add dynamic elements based on evidence and metadata
    if (step.evidence && step.evidence.length > 0) {
      switch (step.step_number) {
        case 1: // Situational Assessment
          if (step.feature_quality_score !== undefined) {
            summary += ` Data quality: ${(step.feature_quality_score * 100).toFixed(0)}%.`
          }
          break
        case 2: // Historical Context
          const similarContexts = step.evidence.find(e => e.includes('similar historical contexts'))
          if (similarContexts) {
            const match = similarContexts.match(/Found (\d+)/)
            if (match) {
              summary += ` Found ${match[1]} relevant cases.`
            }
          }
          if (step.similarity_score !== undefined) {
            summary += ` Avg similarity: ${(step.similarity_score * 100).toFixed(0)}%.`
          }
          break
        case 3: // Model Consensus
          const consensusMatch = step.evidence.find(e => e.includes('models, avg confidence'))
          if (consensusMatch) {
            const match = consensusMatch.match(/(\d+) models/)
            if (match) {
              summary += ` Using ${match[1]} model predictions.`
            }
          }
          break
        case 4: // Risk Assessment
          const riskLevel = step.description.match(/Risk level: (\w+)/)?.[1]
          if (riskLevel) {
            summary += ` Current risk: ${riskLevel}.`
          }
          break
        case 5: // Decision Synthesis
          if (step.description && !step.description.includes('HOLD')) {
            summary += ` Recommends: ${step.description.split(' - ')[0]}.`
          }
          break
      }
    }

    // Add confidence level indicator
    const confidencePercent = normalizeConfidenceToPercent(step.confidence)
    if (confidencePercent >= 75) {
      summary += ' (High confidence)'
    } else if (confidencePercent >= 50) {
      summary += ' (Medium confidence)'
    } else {
      summary += ' (Low confidence)'
    }

    return summary
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
            {chainMeta?.timestamp && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>Generated:</span>
                <span className={getDataFreshnessColor(chainMeta.timestamp)}>
                  {formatDateTime(chainMeta.timestamp)}
                </span>
              </div>
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
            const summary = generateStepSummary(step)

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
                      <span
                        className="text-xs text-muted-foreground cursor-help"
                        title={getConfidenceTooltip(step)}
                      >
                        {formatConfidence(stepConfidence)}
                      </span>
                      <div
                        className="w-20 h-2 cursor-help"
                        title={getConfidenceTooltip(step)}
                      >
                        <ConfidenceProgress value={stepConfidence} />
                      </div>
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

        {/* Model Reasoning Section - Integrated */}
        {(modelConsensus || individualModelReasoning) && (
          <div className="mt-4">
            <Accordion type="single" collapsible defaultValue="">
              <AccordionItem value="model-reasoning">
                <AccordionTrigger className="text-left">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <span>Model Reasoning Details</span>
                    <Badge variant="outline" className="text-xs">
                      {Array.isArray(modelConsensus) ? modelConsensus.length : 0} Models
                    </Badge>
                  </div>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="pt-2">
                    <ModelReasoningView
                      modelConsensus={modelConsensus}
                      individualModelReasoning={individualModelReasoning}
                    />
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </div>
        )}

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
