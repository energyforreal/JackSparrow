import { describe, expect, it } from '@jest/globals'

import { performanceMetricsToChartData } from '@/utils/performanceMetrics'

describe('performanceMetricsToChartData', () => {
  it('prefers total_return USD over percent', () => {
    const points = performanceMetricsToChartData({
      total_return: 1500,
      total_return_pct: 7.5,
    })
    expect(points).toHaveLength(1)
    expect(points[0].value).toBe(1500)
    expect(points[0].metricKind).toBe('usd')
  })

  it('uses percent when USD return is absent', () => {
    const points = performanceMetricsToChartData({
      total_return_pct: 12.3,
    })
    expect(points[0].value).toBe(12.3)
    expect(points[0].metricKind).toBe('pct')
  })

  it('returns empty array for null input', () => {
    expect(performanceMetricsToChartData(null)).toEqual([])
  })
})
