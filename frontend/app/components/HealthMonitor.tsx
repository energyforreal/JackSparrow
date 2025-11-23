'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { HealthStatus } from '@/types'
import { CheckCircle2, AlertCircle, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

interface HealthMonitorProps {
  health?: HealthStatus
}

const getStatusIcon = (status: 'up' | 'degraded' | 'down') => {
  switch (status) {
    case 'up':
      return <CheckCircle2 className="h-4 w-4 text-success" />
    case 'degraded':
      return <AlertCircle className="h-4 w-4 text-warning" />
    case 'down':
      return <XCircle className="h-4 w-4 text-error" />
  }
}

const getStatusVariant = (status: 'up' | 'degraded' | 'down') => {
  switch (status) {
    case 'up':
      return 'default'
    case 'degraded':
      return 'secondary'
    case 'down':
      return 'destructive'
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
    ? Object.entries(health.services).map(([name, service]) => ({
        name,
        status: service.status || 'unknown',
        latency: service.latency_ms,
        error: service.error
      }))
    : []

  // Calculate health score percentage (backend returns 0.0-1.0, frontend expects 0-100)
  const healthScore = typeof health.health_score === 'number' 
    ? Math.round(health.health_score * 100) 
    : typeof health.score === 'number'
    ? health.score
    : 0

  return (
    <Card>
      <CardHeader>
        <CardTitle>System Health</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span className="text-muted-foreground">Overall Score</span>
            <span className="font-medium">{healthScore}%</span>
          </div>
          <Progress value={healthScore} className="h-2" />
        </div>

        <div className="space-y-2">
          {servicesArray.map((service) => (
            <div
              key={service.name}
              className="flex items-center justify-between py-2 border-b last:border-0"
            >
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
                <Badge variant={getStatusVariant(service.status as 'up' | 'degraded' | 'down')}>
                  {service.status.toUpperCase()}
                </Badge>
              </div>
            </div>
          ))}
        </div>

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

