'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ConfidenceProgress } from './ConfidenceProgress'
import { Signal, SignalType } from '@/types'
import { cn } from '@/lib/utils'
import { normalizeConfidenceToPercent, formatConfidence } from '@/utils/formatters'
import { DataFreshnessIndicator } from './DataFreshnessIndicator'

interface SignalIndicatorProps {
  signal?: Signal
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

export function SignalIndicator({ signal }: SignalIndicatorProps) {
  if (!signal) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>AI Signal</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No signal available</p>
          <p className="text-xs text-muted-foreground mt-2">
            Ensure models are loaded and agent service is running. Check System Health for model_nodes status.
          </p>
        </CardContent>
      </Card>
    )
  }

  const overallConfidence = normalizeConfidenceToPercent(signal.confidence)

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Signal</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-4">
          <Badge 
            className={cn('px-4 py-2 text-base', getSignalBadgeClasses(signal.signal))}
            aria-label={`Trading signal: ${signal.signal}`}
          >
            {signal.signal.replace('_', ' ')}
          </Badge>
          <div className="flex-1">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-muted-foreground">Confidence</span>
              <span className="font-medium">
                {formatConfidence(overallConfidence)}
              </span>
            </div>
            <ConfidenceProgress 
              value={overallConfidence}
              className="h-2" 
            />
          </div>
        </div>

        {signal.agent_decision_reasoning && (
          <div className="pt-2 border-t">
            <p className="text-sm font-medium mb-1">Agent Decision Reasoning</p>
            <p className="text-xs text-muted-foreground">{signal.agent_decision_reasoning}</p>
          </div>
        )}

        {signal.timestamp && (
          <DataFreshnessIndicator timestamp={signal.timestamp} />
        )}
      </CardContent>
    </Card>
  )
}

