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
import { ModelConsensus, ModelReasoning, SignalType } from '@/types'
import { cn } from '@/lib/utils'

interface ModelReasoningViewProps {
  modelConsensus?: ModelConsensus[]
  individualModelReasoning?: ModelReasoning[]
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

export function ModelReasoningView({
  modelConsensus,
  individualModelReasoning,
}: ModelReasoningViewProps) {
  const hasConsensus = modelConsensus && modelConsensus.length > 0
  const hasReasoning = individualModelReasoning && individualModelReasoning.length > 0

  if (!hasConsensus && !hasReasoning) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Model Reasoning</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No model reasoning data available
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Model Reasoning</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {hasConsensus && (
          <div>
            <h3 className="text-sm font-semibold mb-3">Model Consensus</h3>
            <div className="space-y-3">
              {modelConsensus.map((model, index) => (
                <div
                  key={index}
                  className="flex items-center justify-between p-3 rounded-lg border bg-card"
                >
                  <div className="flex-1">
                    <div className="font-medium text-sm mb-1">
                      {model.model_name}
                    </div>
                    <div className="flex items-center gap-3 mt-2">
                      <Badge
                        className={cn('px-2 py-1 text-xs', getSignalBadgeClasses(model.signal))}
                      >
                        {model.signal.replace('_', ' ')}
                      </Badge>
                      <div className="flex items-center gap-2 flex-1 max-w-xs">
                        <Progress
                          value={typeof model.confidence === 'number' && model.confidence <= 1
                            ? model.confidence * 100
                            : model.confidence}
                          className="h-2"
                        />
                        <span className="text-xs text-muted-foreground whitespace-nowrap">
                          {typeof model.confidence === 'number' && model.confidence <= 1
                            ? (model.confidence * 100).toFixed(1)
                            : model.confidence}%
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {hasReasoning && (
          <div>
            <h3 className="text-sm font-semibold mb-3">Individual Model Reasoning</h3>
            <Accordion type="single" collapsible className="w-full">
              {individualModelReasoning.map((model, index) => (
                <AccordionItem
                  key={index}
                  value={`model-${index}`}
                  className="border rounded-lg mb-2 px-3"
                >
                  <AccordionTrigger>
                    <div className="flex items-center justify-between w-full pr-4">
                      <div className="flex items-center gap-3">
                        <span className="text-sm font-medium">{model.model_name}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted-foreground">
                          {typeof model.confidence === 'number' && model.confidence <= 1
                            ? (model.confidence * 100).toFixed(1)
                            : model.confidence}%
                        </span>
                        <Progress
                          value={typeof model.confidence === 'number' && model.confidence <= 1
                            ? model.confidence * 100
                            : model.confidence}
                          className="w-16 h-2"
                        />
                      </div>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent>
                    <div className="pt-2 pb-2">
                      <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                        {model.reasoning}
                      </p>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
