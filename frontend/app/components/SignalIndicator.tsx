'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ConfidenceProgress } from './ConfidenceProgress'
import { ModelConsensus, Signal, SignalType } from '@/types'
import { cn } from '@/lib/utils'
import { normalizeConfidenceToPercent, formatConfidence } from '@/utils/formatters'
import { DataFreshnessIndicator } from './DataFreshnessIndicator'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'

interface SignalIndicatorProps {
  signal?: Signal
  modelData?: {
    model_consensus?: ModelConsensus[]
    inference_latency_ms?: number
    inference_source?: string
    inference_mode?: string
  } | null
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

export function SignalIndicator({ signal, modelData }: SignalIndicatorProps) {
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
  const modelConsensus = signal.model_consensus && signal.model_consensus.length > 0
    ? signal.model_consensus
    : modelData?.model_consensus && modelData.model_consensus.length > 0
      ? modelData.model_consensus
      : []
  const latencyMs = signal.inference_latency_ms ?? modelData?.inference_latency_ms
  const inferenceMode = signal.inference_mode ?? modelData?.inference_mode
  const inferenceSource = signal.inference_source ?? modelData?.inference_source

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>AI Signal</CardTitle>
          {(inferenceMode === 'fallback' || inferenceMode === 'degraded' || inferenceSource) && (
            <Badge variant="outline" className="text-xs font-normal">
              {inferenceMode === 'fallback' && 'Agent fallback'}
              {inferenceMode === 'degraded' && 'Degraded'}
              {inferenceMode === 'primary' && inferenceSource === 'model_service' && 'Model service'}
              {!inferenceMode && inferenceSource === 'agent' && 'Agent'}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-4">
          <Badge 
            className={cn('px-4 py-2 text-base', getSignalBadgeClasses(signal.signal))}
            aria-label={`Trading signal: ${signal.signal}`}
          >
            {signal.signal ? signal.signal.toString().replace('_', ' ') : 'Unknown'}
          </Badge>
          {latencyMs != null && (
            <span className="text-xs text-muted-foreground">Latency: {Math.round(latencyMs)}ms</span>
          )}
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

        {modelConsensus.length > 0 && (
          <div className="pt-2 border-t">
            <Accordion type="single" collapsible defaultValue="models">
              <AccordionItem value="models">
                <AccordionTrigger className="text-sm font-medium text-left">
                  Individual Models ({modelConsensus.length})
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-3 mt-1">
                    {modelConsensus.map((model) => {
                      const percent = normalizeConfidenceToPercent(model.confidence)
                      return (
                        <div
                          key={model.model_name}
                          className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="text-sm font-medium truncate">
                              {model.model_name}
                            </div>
                            <div className="mt-1 flex items-center gap-3">
                              <Badge
                                className={cn(
                                  'px-2 py-0.5 text-xs',
                                  getSignalBadgeClasses(model.signal)
                                )}
                              >
                                {model.signal.replace('_', ' ')}
                              </Badge>
                              <div className="flex items-center gap-2 flex-1">
                                <ConfidenceProgress
                                  value={percent}
                                  className="h-1.5"
                                />
                                <span className="text-xs text-muted-foreground tabular-nums">
                                  {formatConfidence(percent)}
                                </span>
                              </div>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </div>
        )}

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

