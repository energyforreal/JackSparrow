'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Signal, SignalType } from '@/types'
import { cn } from '@/lib/utils'

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

  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Signal</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-4">
          <Badge className={cn('px-4 py-2 text-base', getSignalBadgeClasses(signal.signal))}>
            {signal.signal.replace('_', ' ')}
          </Badge>
          <div className="flex-1">
            <div className="flex justify-between text-sm mb-1">
              <span className="text-muted-foreground">Confidence</span>
              <span className="font-medium">
                {typeof signal.confidence === 'number' 
                  ? (signal.confidence > 1 && signal.confidence <= 100 
                      ? `${signal.confidence.toFixed(1)}%` 
                      : signal.confidence > 1 
                        ? `${signal.confidence}%` 
                        : `${(signal.confidence * 100).toFixed(1)}%`)
                  : `${signal.confidence}%`}
              </span>
            </div>
            <Progress 
              value={typeof signal.confidence === 'number' && signal.confidence <= 1 
                ? signal.confidence * 100 
                : signal.confidence} 
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
          <div className="text-xs text-muted-foreground">
            Last update: {new Date(signal.timestamp).toLocaleTimeString()}
          </div>
        )}

        {signal.model_consensus && signal.model_consensus.length > 0 && (
          <Accordion type="single" collapsible className="w-full">
            <AccordionItem value="consensus">
              <AccordionTrigger>Model Consensus</AccordionTrigger>
              <AccordionContent>
                <div className="space-y-2">
                  {signal.model_consensus.map((model, index) => (
                    <div
                      key={index}
                      className="flex items-center justify-between text-sm"
                    >
                      <span className="font-medium">{model.model_name}:</span>
                      <div className="flex items-center gap-2">
                        <Badge
                          variant="outline"
                          className={getSignalBadgeClasses(model.signal)}
                        >
                          {model.signal.replace('_', ' ')}
                        </Badge>
                        <span className="text-muted-foreground">
                          ({typeof model.confidence === 'number' && model.confidence <= 1 
                            ? (model.confidence * 100).toFixed(1) 
                            : model.confidence}%)
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        )}

        {signal.individual_model_reasoning && signal.individual_model_reasoning.length > 0 && (
          <Accordion type="single" collapsible className="w-full">
            <AccordionItem value="model_reasoning">
              <AccordionTrigger>Individual Model Reasoning</AccordionTrigger>
              <AccordionContent>
                <div className="space-y-3">
                  {signal.individual_model_reasoning.map((model, index) => (
                    <div key={index} className="border-l-2 border-muted pl-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-medium text-sm">{model.model_name}</span>
                        <span className="text-xs text-muted-foreground">
                          {typeof model.confidence === 'number' && model.confidence <= 1 
                            ? (model.confidence * 100).toFixed(1) 
                            : model.confidence}% confidence
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground">{model.reasoning}</p>
                    </div>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        )}
      </CardContent>
    </Card>
  )
}

