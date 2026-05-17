import { describe, expect, it } from '@jest/globals'

import {
  computeTradeDurationSeconds,
  formatTradeDuration,
  isLongSide,
  sideBadgeVariant,
} from '@/utils/tradingDisplay'

describe('tradingDisplay', () => {
  it('treats LONG as long side for badges', () => {
    expect(isLongSide('LONG')).toBe(true)
    expect(sideBadgeVariant('LONG')).toBe('default')
    expect(sideBadgeVariant('SHORT')).toBe('destructive')
  })

  it('computes duration from timestamps when duration_seconds is zero', () => {
    const sec = computeTradeDurationSeconds(
      0,
      '2026-04-14T10:00:00Z',
      '2026-04-14T10:00:02Z'
    )
    expect(sec).toBe(2)
    expect(formatTradeDuration(sec)).toBe('2s')
  })
})
