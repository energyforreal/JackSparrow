'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { ReasoningStep } from '@/types'

interface ReasoningChainViewProps {
  reasoningChain?: ReasoningStep[]
  overallConfidence?: number
}

export function ReasoningChainView({
  reasoningChain,
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
            No reasoning chain available
          </p>
        </CardContent>
      </Card>
    )
  }

  const sortedSteps = [...reasoningChain].sort(
    (a, b) => a.step_number - b.step_number
  )
  const conclusion = sortedSteps[sortedSteps.length - 1]

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Agent Reasoning Chain</CardTitle>
          {overallConfidence !== undefined && (
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

        {conclusion && (
          <Card className="mt-4 bg-accent/50 border-accent">
            <CardHeader>
              <CardTitle className="text-lg">Conclusion</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm">{conclusion.content}</p>
              {conclusion.evidence && conclusion.evidence.length > 0 && (
                <div className="flex flex-wrap gap-2 mt-3">
                  {conclusion.evidence.map((evidence, index) => (
                    <Badge key={index} variant="outline" className="text-xs">
                      {evidence}
                    </Badge>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </CardContent>
    </Card>
  )
}

