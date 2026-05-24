import { describe, expect, it } from '@jest/globals'

import { resolveDisplayConfidence } from '@/utils/signalConfidence'

describe('resolveDisplayConfidence', () => {
  it('prefers final_confidence over policy confidence', () => {
    const result = resolveDisplayConfidence({
      confidence: 0.3,
      final_confidence: 0.62,
    })
    expect(result.percent).toBeCloseTo(62, 5)
    expect(result.source).toBe('reasoning')
    expect(result.usedPolicyFallback).toBe(false)
    expect(result.policyPercent).toBeCloseTo(30, 5)
  })

  it('falls back to policy confidence when final_confidence is missing', () => {
    const result = resolveDisplayConfidence({
      confidence: 0.3,
    })
    expect(result.percent).toBeCloseTo(30, 5)
    expect(result.source).toBe('policy')
    expect(result.usedPolicyFallback).toBe(true)
  })

  it('accepts percent-scale inputs', () => {
    const result = resolveDisplayConfidence({
      confidence: 30,
      final_confidence: 68,
    })
    expect(result.percent).toBeCloseTo(68, 5)
    expect(result.policyPercent).toBeCloseTo(30, 5)
  })
})
