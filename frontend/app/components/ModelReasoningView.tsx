'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Badge } from '@/components/ui/badge'
import { ModelConsensus, ModelReasoning, SignalType } from '@/types'
import { cn } from '@/lib/utils'
import { normalizeConfidenceToPercent } from '@/utils/formatters'

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
                        value={normalizeConfidenceToPercent(model.confidence)}
                        className="h-2"
                      />
                      <span className="text-xs text-muted-foreground whitespace-nowrap">
                        {normalizeConfidenceToPercent(model.confidence).toFixed(1)}%
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
