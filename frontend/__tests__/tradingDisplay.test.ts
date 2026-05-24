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

  it('returns em dash when entry time is missing', () => {
    const sec = computeTradeDurationSeconds(
      undefined,
      undefined,
      '2026-04-14T10:00:02Z'
    )
    expect(sec).toBeNull()
    expect(formatTradeDuration(sec)).toBe('—')
  })

  it('returns em dash when entry and exit collapse to the same instant', () => {
    const ts = '2026-04-14T10:00:02Z'
    const sec = computeTradeDurationSeconds(undefined, ts, ts)
    expect(sec).toBeNull()
    expect(formatTradeDuration(sec)).toBe('—')
  })
})
