import { describe, expect, it } from '@jest/globals'
import { unrealizedPnlPercentOnMargin } from '@/utils/portfolioMetrics'

describe('unrealizedPnlPercentOnMargin', () => {
  it('returns ratio unrealized / margin when margin > 0', () => {
    expect(unrealizedPnlPercentOnMargin(22.44, 1183.68)).toBeCloseTo(22.44 / 1183.68, 10)
  })

  it('returns null when margin_used is zero', () => {
    expect(unrealizedPnlPercentOnMargin(10, 0)).toBeNull()
    expect(unrealizedPnlPercentOnMargin(10, -1)).toBeNull()
  })

  it('returns null for non-finite inputs', () => {
    expect(unrealizedPnlPercentOnMargin(Number.NaN, 100)).toBeNull()
    expect(unrealizedPnlPercentOnMargin(10, Number.NaN)).toBeNull()
  })

  it('allows zero unrealized PnL', () => {
    expect(unrealizedPnlPercentOnMargin(0, 500)).toBe(0)
  })
})
