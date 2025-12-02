'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfidenceProgress } from './ConfidenceProgress'
import { Badge } from '@/components/ui/badge'
import { ModelConsensus, ModelReasoning, SignalType } from '@/types'
import { cn } from '@/lib/utils'
import { normalizeConfidenceToPercent, formatConfidence } from '@/utils/formatters'

interface ModelReasoningViewProps {
  modelConsensus?: ModelConsensus[]
  // Individual model reasoning is still accepted for future use,
  // but intentionally not rendered to keep the UI focused.
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

  if (!hasConsensus) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Model Reasoning</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <div className="text-muted-foreground mb-2">
              <svg
                className="mx-auto h-10 w-10 text-muted-foreground/50"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                />
              </svg>
            </div>
            <p className="text-sm font-medium text-foreground mb-1">
              No Model Reasoning Data Available
            </p>
            <p className="text-xs text-muted-foreground max-w-sm">
              Model consensus and reasoning will appear here when the agent makes a prediction. 
              This data is generated during the decision-making process.
            </p>
          </div>
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
                      <ConfidenceProgress
                        value={model.confidence}
                        className="h-2"
                      />
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {formatConfidence(model.confidence)}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
