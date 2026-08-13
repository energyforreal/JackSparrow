import { describe, expect, it } from '@jest/globals'

import {
  isHoldNonActionableDisplay,
  isTransformerMtfPath,
  resolveConfidenceBand,
  resolveDisplayConfidence,
  resolvePolicyEntryPercent,
  resolveReasonCodes,
  resolveSignalEntryMetrics,
  resolveTradeScore,
} from '@/utils/signalConfidence'

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

  it('surfaces signal_strength when provided', () => {
    const result = resolveDisplayConfidence({
      confidence: 0.55,
      final_confidence: 0.62,
      signal_strength: 0.71,
    })
    expect(result.signalStrengthPercent).toBeCloseTo(71, 5)
  })
})

describe('resolvePolicyEntryPercent', () => {
  it('prefers policy_confidence over reasoning final', () => {
    expect(
      resolvePolicyEntryPercent({
        confidence: 0.24,
        final_confidence: 0.24,
        policy_confidence: 0.31,
      })
    ).toBeCloseTo(31, 5)
  })
})

describe('resolveTradeScore', () => {
  it('reads top-level trade_score', () => {
    expect(resolveTradeScore({ trade_score: 93 })?.score).toBe(93)
  })

  it('reads trade_score object with passed flag', () => {
    expect(
      resolveTradeScore({ trade_score: { score: 88, passed: true } })
    ).toEqual({ score: 88, passed: true })
  })

  it('falls back to introspection', () => {
    expect(
      resolveTradeScore({
        agent_introspection: { trade_score: 88, trade_score_pass: true },
      })
    ).toEqual({ score: 88, passed: true })
  })
})

describe('resolveSignalEntryMetrics', () => {
  it('flags split when reasoning and policy differ', () => {
    const m = resolveSignalEntryMetrics({
      confidence: 0.3,
      final_confidence: 0.24,
    })
    expect(m?.showSplitConfidence).toBe(true)
    expect(m?.reasoningPercent).toBeCloseTo(24, 5)
    expect(m?.policyEntryPercent).toBeCloseTo(30, 5)
    expect(m?.tradeScore).toBeUndefined()
  })

  it('includes trade score when present', () => {
    const m = resolveSignalEntryMetrics({
      confidence: 0.3,
      final_confidence: 0.24,
      trade_score: 93,
      agent_introspection: { trade_score_pass: true },
    })
    expect(m?.tradeScore?.score).toBe(93)
    expect(m?.tradeScore?.passed).toBe(true)
  })

  it('zeros confidence bars for non-actionable HOLD', () => {
    const m = resolveSignalEntryMetrics({
      signal: 'HOLD',
      confidence: 0.85,
      final_confidence: 0.72,
      is_actionable_entry: false,
    })
    expect(m?.reasoningPercent).toBe(0)
    expect(m?.policyEntryPercent).toBe(0)
    expect(m?.showSplitConfidence).toBe(false)
  })

  it('hides trade score on transformer_mtf path', () => {
    const m = resolveSignalEntryMetrics({
      confidence: 0.5,
      trade_score: 90,
      decision_path: 'transformer_mtf',
    } as Parameters<typeof resolveSignalEntryMetrics>[0])
    expect(m?.tradeScore).toBeUndefined()
  })
})

describe('isHoldNonActionableDisplay', () => {
  it('returns true for HOLD without actionable flag', () => {
    expect(isHoldNonActionableDisplay({ signal: 'HOLD' })).toBe(true)
  })

  it('returns false for actionable BUY', () => {
    expect(
      isHoldNonActionableDisplay({ signal: 'BUY', is_actionable_entry: true })
    ).toBe(false)
  })
})

describe('resolveConfidenceBand', () => {
  it('uses size_scale from execution_plan for reduced band', () => {
    const band = resolveConfidenceBand({
      signal: 'BUY',
      confidence: 0.62,
      is_actionable_entry: true,
      execution_plan: { size_scale: 0.7, size_fraction: 0.42, rr_soft_action: 'reduce_size' },
    })
    expect(band.band).toBe('reduced')
    expect(band.sizeScale).toBe(0.7)
    expect(band.rrSoftAction).toBe('reduce_size')
  })

  it('returns full when size_scale is 1', () => {
    const band = resolveConfidenceBand({
      signal: 'BUY',
      confidence: 0.8,
      execution_plan: { size_scale: 1, size_fraction: 0.6 },
    })
    expect(band.band).toBe('full')
  })

  it('returns hold for HOLD signal', () => {
    expect(resolveConfidenceBand({ signal: 'HOLD', confidence: 0.2 }).band).toBe('hold')
  })
})

describe('isTransformerMtfPath / resolveReasonCodes', () => {
  it('detects transformer_mtf decision_path', () => {
    expect(isTransformerMtfPath({ decision_path: 'transformer_mtf' })).toBe(true)
    expect(isTransformerMtfPath({ decision_path: 'legacy' })).toBe(false)
  })

  it('prefers execution_plan reason codes', () => {
    expect(
      resolveReasonCodes({
        policy_reason_codes: ['a'],
        execution_plan: { reason_codes: ['path_rr_reduce_size', 'mtf_aligned'] },
      })
    ).toEqual(['path_rr_reduce_size', 'mtf_aligned'])
  })
})
