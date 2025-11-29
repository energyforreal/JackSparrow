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
              <span className="font-medium">{signal.confidence}%</span>
            </div>
            <Progress value={signal.confidence} className="h-2" />
          </div>
        </div>

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
                          ({model.confidence}%)
                        </span>
                      </div>
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

