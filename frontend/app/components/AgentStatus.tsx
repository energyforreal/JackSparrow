'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Eye, Brain, Zap, AlertTriangle, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { formatTime } from '@/utils/formatters'
import { DataFreshnessIndicator } from './DataFreshnessIndicator'

interface AgentStatusProps {
  state: string
  lastUpdate: Date
  message?: string
  isConnected?: boolean
}

const getStateConfig = (state: string) => {
  switch (state) {
    case 'MONITORING':
    case 'OBSERVING':
      return {
        color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
        icon: Eye,
        label: 'Monitoring Markets',
        bgColor: 'bg-emerald-500',
      }
    case 'THINKING':
    case 'DELIBERATING':
    case 'ANALYZING':
      return {
        color: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
        icon: Brain,
        label: 'Analyzing Signals',
        bgColor: 'bg-blue-500',
      }
    case 'EXECUTING':
    case 'TRADING':
      return {
        color: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
        icon: Zap,
        label: 'Active Trade',
        bgColor: 'bg-amber-500',
      }
    case 'DEGRADED':
      return {
        color: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
        icon: AlertTriangle,
        label: 'Degraded Performance',
        bgColor: 'bg-yellow-500',
      }
    case 'EMERGENCY_STOP':
      return {
        color: 'bg-red-500/10 text-red-400 border-red-500/20',
        icon: AlertCircle,
        label: 'Emergency Stop',
        bgColor: 'bg-red-500',
      }
    default:
      return {
        color: 'bg-muted text-muted-foreground border-border',
        icon: AlertCircle,
        label: 'Unknown',
        bgColor: 'bg-gray-500',
      }
  }
}

export function AgentStatus({
  state,
  lastUpdate,
  message,
  isConnected = false,
}: AgentStatusProps) {
  const config = getStateConfig(state)
  const Icon = config.icon

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent Status</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Badge
          variant="outline"
          className={cn(
            'flex items-center gap-2 px-3 py-2 text-sm font-medium w-fit',
            config.color
          )}
          role="status"
          aria-live="polite"
          aria-label={`Agent status: ${state}`}
        >
          <span className={cn('h-2 w-2 rounded-full', config.bgColor)} aria-hidden="true" />
          <Icon className="h-4 w-4" />
          <span>{state || 'UNKNOWN'}</span>
        </Badge>

        <div className="space-y-1">
          <p className="text-sm font-medium">{config.label}</p>
          {message && (
            <p className="text-sm text-muted-foreground">{message}</p>
          )}
        </div>

        <div className="flex items-center justify-between text-xs pt-2 border-t">
          <DataFreshnessIndicator timestamp={lastUpdate} />
          <div className="flex items-center gap-1">
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                isConnected ? 'bg-success' : 'bg-error'
              )}
            />
            <span className={cn(
              isConnected ? 'text-success' : 'text-error'
            )}>
              {isConnected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

