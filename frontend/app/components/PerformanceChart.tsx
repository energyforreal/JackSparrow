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
          <p className="text-sm text-muted-foreground">No performance data available</p>
        </CardContent>
      </Card>
    )
  }

  const filteredData = data.slice(-getDataPoints(period))

  return (
    <Card>
      <CardHeader>
        <CardTitle>Performance Chart</CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs value={period} onValueChange={(v) => setPeriod(v as TimePeriod)}>
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="1d">1d</TabsTrigger>
            <TabsTrigger value="7d">7d</TabsTrigger>
            <TabsTrigger value="30d">30d</TabsTrigger>
            <TabsTrigger value="all">All</TabsTrigger>
          </TabsList>
          <TabsContent value={period} className="mt-4">
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={filteredData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => {
                    const date = new Date(value)
                    return period === '1d'
                      ? date.toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                        })
                      : date.toLocaleDateString([], {
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
                  formatter={(value: number) => [
                    `$${value.toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}`,
                    'Portfolio Value',
                  ]}
                  labelFormatter={(label) => {
                    const date = new Date(label)
                    return date.toLocaleString()
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="hsl(var(--primary))"
                  strokeWidth={2}
                  dot={false}
                />
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

