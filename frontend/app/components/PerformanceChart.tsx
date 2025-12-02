'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Dot,
} from 'recharts'

interface PerformanceChartProps {
  data?: Array<{ date: string; value: number }>
}

type TimePeriod = '1d' | '7d' | '30d' | 'all'

export function PerformanceChart({ data }: PerformanceChartProps) {
  const [period, setPeriod] = useState<TimePeriod>('7d')

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
              Performance data will appear here once trades are executed. 
              The chart tracks portfolio value over time.
            </p>
          </div>
        </CardContent>
      </Card>
    )
  }

  const filteredData = data.slice(-getDataPoints(period))

  return (
    <Card role="region" aria-label="Portfolio Performance Chart">
      <CardHeader>
        <CardTitle>Performance Chart</CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs value={period} onValueChange={(v) => setPeriod(v as TimePeriod)}>
          <TabsList className="grid w-full grid-cols-4" role="tablist" aria-label="Time period selection">
            <TabsTrigger value="1d" role="tab" aria-label="1 day view">1d</TabsTrigger>
            <TabsTrigger value="7d" role="tab" aria-label="7 day view">7d</TabsTrigger>
            <TabsTrigger value="30d" role="tab" aria-label="30 day view">30d</TabsTrigger>
            <TabsTrigger value="all" role="tab" aria-label="All time view">All</TabsTrigger>
          </TabsList>
          <TabsContent value={period} className="mt-4" role="tabpanel" aria-label={`Performance chart for ${period}`}>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart 
                data={filteredData}
                aria-label="Portfolio value over time"
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => {
                    const date = new Date(value)
                    return period === '1d'
                      ? date.toLocaleTimeString('en-IN', {
                          timeZone: 'Asia/Kolkata',
                          hour: '2-digit',
                          minute: '2-digit',
                        })
                      : date.toLocaleDateString('en-IN', {
                          timeZone: 'Asia/Kolkata',
                          month: 'short',
                          day: 'numeric',
                        })
                  }}
                />
                <YAxis
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => `$${value.toLocaleString()}`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'hsl(var(--card))',
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '0.5rem',
                    padding: '0.75rem',
                  }}
                  formatter={(value: number) => [
                    `$${value.toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}`,
                    'Portfolio Value',
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
                  cursor={{ stroke: 'hsl(var(--primary))', strokeWidth: 1, strokeDasharray: '3 3' }}
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
                {filteredData.length > 0 && filteredData[0]?.value && (
                  <ReferenceLine 
                    y={filteredData[0].value} 
                    stroke="hsl(var(--muted-foreground))" 
                    strokeDasharray="2 2"
                    label={{ value: 'Starting Value', position: 'right', fill: 'hsl(var(--muted-foreground))' }}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

function getDataPoints(period: TimePeriod): number {
  switch (period) {
    case '1d':
      return 24 // hourly data points
    case '7d':
      return 168 // hourly data points for 7 days
    case '30d':
      return 30 // daily data points
    case 'all':
      return Infinity
    default:
      return 168
  }
}

