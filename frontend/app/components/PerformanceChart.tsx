'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'

export type PerformanceMetricKind = 'usd' | 'pct'

export interface PerformanceDataPoint {
  date: string
  value: number
  metricKind?: PerformanceMetricKind
}

interface PerformanceChartProps {
  data?: PerformanceDataPoint[]
}

function formatPerformanceValue(value: number, metricKind: PerformanceMetricKind): string {
  if (metricKind === 'pct') {
    return `${value.toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}%`
  }
  return `$${value.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function resolveMetricKind(data: PerformanceDataPoint[]): PerformanceMetricKind {
  const explicit = data.find((p) => p.metricKind)?.metricKind
  return explicit ?? 'usd'
}

export function PerformanceChart({ data }: PerformanceChartProps) {
  if (!data || data.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Performance Chart</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="text-muted-foreground mb-2">
              <svg
                className="mx-auto h-12 w-12 text-muted-foreground/50"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                />
              </svg>
            </div>
            <p className="text-sm font-medium text-foreground mb-1">
              No Performance Data Available
            </p>
            <p className="text-xs text-muted-foreground max-w-sm">
              Performance data will appear here once trades are executed. The chart tracks
              cumulative return from closed positions.
            </p>
          </div>
        </CardContent>
      </Card>
    )
  }

  const metricKind = resolveMetricKind(data)
  const metricLabel = metricKind === 'pct' ? 'Total Return (%)' : 'Total Return (USD)'
  const isSnapshot = data.length === 1
  const baselineValue = data[0]?.value

  return (
    <Card role="region" aria-label="Portfolio Performance Chart">
      <CardHeader>
        <CardTitle>Performance Chart</CardTitle>
        <p className="text-xs text-muted-foreground">{metricLabel}</p>
      </CardHeader>
      <CardContent>
        {isSnapshot ? (
          <div className="flex flex-col items-center justify-center py-10 text-center space-y-2">
            <p className="text-3xl font-semibold tabular-nums">
              {formatPerformanceValue(data[0].value, metricKind)}
            </p>
            <p className="text-xs text-muted-foreground max-w-sm">
              Snapshot from closed-position aggregates. A time series will appear when historical
              performance points are available.
            </p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={data} aria-label="Total return over time">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 12 }}
                tickFormatter={(value) => {
                  const date = new Date(value)
                  return date.toLocaleDateString('en-IN', {
                    timeZone: 'Asia/Kolkata',
                    month: 'short',
                    day: 'numeric',
                  })
                }}
              />
              <YAxis
                tick={{ fontSize: 12 }}
                tickFormatter={(value) =>
                  metricKind === 'pct'
                    ? `${Number(value).toFixed(1)}%`
                    : `$${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
                }
              />
              <Tooltip
                shared
                trigger="hover"
                wrapperStyle={{ zIndex: 50 }}
                contentStyle={{
                  backgroundColor: 'hsl(var(--card))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '0.5rem',
                  padding: '0.75rem',
                  boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
                }}
                formatter={(value: number) => [
                  formatPerformanceValue(value, metricKind),
                  metricLabel,
                ]}
                labelFormatter={(label) => {
                  const date = new Date(label)
                  return date.toLocaleString('en-IN', {
                    timeZone: 'Asia/Kolkata',
                    weekday: 'short',
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit',
                  })
                }}
                cursor={{
                  stroke: 'hsl(var(--primary))',
                  strokeWidth: 2,
                  strokeDasharray: '4 4',
                }}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="hsl(var(--primary))"
                strokeWidth={2}
                dot={false}
                activeDot={{
                  r: 6,
                  fill: 'hsl(var(--primary))',
                  stroke: 'hsl(var(--background))',
                  strokeWidth: 2,
                }}
                animationDuration={300}
              />
              {baselineValue != null && Number.isFinite(baselineValue) && (
                <ReferenceLine
                  y={baselineValue}
                  stroke="hsl(var(--muted-foreground))"
                  strokeDasharray="2 2"
                  label={{
                    value: 'Starting Value',
                    position: 'right',
                    fill: 'hsl(var(--muted-foreground))',
                  }}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
