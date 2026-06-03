import { describe, expect, it } from '@jest/globals'

import {
  resolveDisplayConfidence,
  resolvePolicyEntryPercent,
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
})
