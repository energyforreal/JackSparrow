'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ConfidenceProgress } from './ConfidenceProgress'
import { HealthStatus } from '@/types'
import { CheckCircle2, AlertCircle, XCircle } from 'lucide-react'

interface HealthMonitorProps {
  health?: HealthStatus
}

const getStatusIcon = (status: 'up' | 'degraded' | 'down' | 'unknown') => {
  switch (status) {
    case 'up':
      return <CheckCircle2 className="h-4 w-4 text-success" />
    case 'degraded':
      return <AlertCircle className="h-4 w-4 text-warning" />
    case 'down':
      return <XCircle className="h-4 w-4 text-error" />
    case 'unknown':
      return <AlertCircle className="h-4 w-4 text-muted-foreground" />
    default:
      return <AlertCircle className="h-4 w-4 text-muted-foreground" />
  }
}

const getStatusVariant = (status: 'up' | 'degraded' | 'down' | 'unknown') => {
  switch (status) {
    case 'up':
      return 'default'
    case 'degraded':
      return 'secondary'
    case 'down':
      return 'destructive'
    case 'unknown':
      return 'outline'
    default:
      return 'outline'
  }
}

export function HealthMonitor({ health }: HealthMonitorProps) {
  if (!health) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>System Health</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">Loading health status...</p>
        </CardContent>
      </Card>
    )
  }

  // Convert services object/dictionary to array format
  // Backend returns services as a dictionary: { "database": {...}, "redis": {...} }
  // Frontend expects an array: [{ name: "database", ... }, { name: "redis", ... }]
  const servicesArray = Array.isArray(health.services)
    ? health.services
    : health.services && typeof health.services === 'object'
    ? Object.entries(health.services).map(([name, service]) => {
        const s = service && typeof service === 'object' ? service : {}
        return {
          name,
          status: (s as { status?: string }).status || 'unknown',
          latency: (s as { latency_ms?: number }).latency_ms,
          error: (s as { error?: string }).error,
          details: (s as { details?: unknown }).details
        }
      })
    : []

  // Health score is now standardized to 0-100 range in WebSocket messages
  // API still returns 0.0-1.0, but WebSocket sends 0-100
  // Handle both formats for backward compatibility
  const healthScore = typeof health.health_score === 'number'
    ? (health.health_score > 1 ? health.health_score : Math.round(health.health_score * 100)) // If > 1, already in 0-100 range
    : typeof health.score === 'number'
    ? (health.score > 1 ? health.score : Math.round(health.score * 100))
    : 0

  return (
    <Card role="region" aria-label="System Health Status">
      <CardHeader>
        <CardTitle>System Health</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-muted-foreground">Overall Score</span>
            <span className="font-medium">{healthScore}%</span>
          </div>
          <ConfidenceProgress value={healthScore} className="h-2" variant="health" />
        </div>

        {typeof health.trading_ready === 'boolean' && (
          <p className="text-sm text-muted-foreground">
            Paper trading: {health.trading_ready ? 'Ready' : 'Unavailable (models not ready)'}
          </p>
        )}

        <div className="space-y-2">
          {servicesArray.map((service) => {
            const details = service.details || {}
            const healthyModels =
              typeof details.healthy_models === 'number' ? details.healthy_models : undefined
            const totalModels =
              typeof details.total_models === 'number' ? details.total_models : undefined
            const note = typeof details.note === 'string' ? details.note : undefined
            const shouldShowDetails =
              service.status === 'unknown' &&
              (note || (healthyModels !== undefined && totalModels !== undefined))

            return (
              <div
                key={service.name}
                className="py-2 border-b last:border-0"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {getStatusIcon(service.status)}
                    <span className="text-sm font-medium">{service.name}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {service.latency !== undefined && service.latency !== null && (
                      <span className="text-xs text-muted-foreground">
                        {service.latency}ms
                      </span>
                    )}
                    <Badge variant={getStatusVariant(service.status as 'up' | 'degraded' | 'down' | 'unknown')}>
                      {service.status.toUpperCase()}
                    </Badge>
                  </div>
                </div>
                {shouldShowDetails && (
                  <div className="mt-2 text-xs text-muted-foreground space-y-1">
                    {healthyModels !== undefined && totalModels !== undefined && (
                      <p>
                        Healthy models: {healthyModels}/{totalModels}
                      </p>
                    )}
                    {note && <p>{note}</p>}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {(() => {
          const modelServing = servicesArray.find((s) => s.name === 'model_serving')
          if (modelServing && modelServing.status !== 'up') {
            return (
              <p className="text-xs text-muted-foreground mt-2">
                When model serving is unavailable, predictions use the agent fallback path. Signal card will show &quot;Agent fallback&quot; or &quot;Degraded&quot; when applicable.
              </p>
            )
          }
          return null
        })()}

        {health.degradation_reasons &&
          Array.isArray(health.degradation_reasons) &&
          health.degradation_reasons.length > 0 && (
            <div className="mt-4 p-3 bg-warning/10 border border-warning/20 rounded-md">
              <p className="text-sm font-medium text-warning mb-1">
                Degradation Reasons:
              </p>
              <ul className="text-xs text-muted-foreground list-disc list-inside space-y-1">
                {health.degradation_reasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
            </div>
          )}
      </CardContent>
    </Card>
  )
}

