import type { PerformanceDataPoint } from '@/app/components/PerformanceChart'

/** Map backend performance metrics to chart data points (bootstrap + WS). */
export function performanceMetricsToChartData(
  metrics: Record<string, unknown> | null | undefined
): PerformanceDataPoint[] {
  if (!metrics || typeof metrics !== 'object') return []

  const hasUsdReturn = typeof metrics.total_return === 'number'
  const hasPctReturn = typeof metrics.total_return_pct === 'number'
  const value = hasUsdReturn
    ? (metrics.total_return as number)
    : hasPctReturn
      ? (metrics.total_return_pct as number)
      : 0
  const metricKind: PerformanceDataPoint['metricKind'] = hasUsdReturn
    ? 'usd'
    : hasPctReturn
      ? 'pct'
      : 'usd'

  return [{ date: new Date().toISOString(), value, metricKind }]
}
