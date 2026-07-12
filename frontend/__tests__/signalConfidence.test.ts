import { describe, expect, it } from '@jest/globals'

import {
  isHoldNonActionableDisplay,
  isShortSideSignal,
  resolveDirectionalEdge,
  resolveDisplayConfidence,
  resolveEconomicEdgeBarPercent,
  resolveHeroMetrics,
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

  it('reads trade_score_detail with components', () => {
    const ts = resolveTradeScore({
      trade_score_detail: {
        score: 88,
        passed: true,
        components: { thesis: 20, ml: 15 },
      },
    })
    expect(ts?.score).toBe(88)
    expect(ts?.passed).toBe(true)
    expect(ts?.components?.thesis).toBe(20)
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

  it('preserves confidence values for non-actionable HOLD (dimmed in UI)', () => {
    const m = resolveSignalEntryMetrics({
      signal: 'HOLD',
      confidence: 0.85,
      final_confidence: 0.72,
      is_actionable_entry: false,
    })
    expect(m?.reasoningPercent).toBeCloseTo(72, 5)
    expect(m?.policyEntryPercent).toBeCloseTo(85, 5)
    expect(m?.holdDim).toBe(true)
    expect(m?.showSplitConfidence).toBe(true)
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

describe('resolveHeroMetrics', () => {
  it('returns orthogonal hero fields', () => {
    const h = resolveHeroMetrics({
      signal: 'LONG',
      confidence: 0.7,
      policy_confidence: 0.7,
      final_confidence: 0.72,
      economic_edge: 0.003,
      threshold: 0.005,
      entry_proba_margin: 0.25,
      trade_score_detail: { score: 80, passed: true, components: { thesis: 20 } },
      reasoning_confidence_raw: 0.6,
    })
    expect(h?.policyEntryPercent).toBeCloseTo(70, 5)
    expect(h?.economicEdge).toBeCloseTo(0.003, 5)
    expect(h?.entryMarginPercent).toBeCloseTo(25, 5)
    expect(h?.tradeScore?.score).toBe(80)
    expect(h?.reasoningRawPercent).toBeCloseTo(60, 5)
  })

  it('computes Gate5-aligned short edge from expected_return (not long er-thr)', () => {
    const h = resolveHeroMetrics({
      signal: 'SHORT',
      confidence: 0.3,
      expected_return: -0.015,
      threshold: 0.005,
      // Misleading long-style edge must not win when ER/thr are present
      economic_edge: -0.02,
    })
    // short: -(-0.015) - 0.005 = 0.010
    expect(h?.economicEdge).toBeCloseTo(0.01, 5)
  })
})

describe('resolveDirectionalEdge', () => {
  it('matches Gate5 long and short formulas', () => {
    expect(resolveDirectionalEdge(0.015, 0.005, false)).toBeCloseTo(0.01, 5)
    expect(resolveDirectionalEdge(-0.015, 0.005, true)).toBeCloseTo(0.01, 5)
    expect(isShortSideSignal({ signal: 'STRONG SHORT' })).toBe(true)
    expect(isShortSideSignal({ signal: 'HOLD', thesis_signal: 'SHORT' })).toBe(true)
  })
})

describe('resolveEconomicEdgeBarPercent', () => {
  it('centers bar at threshold crossing', () => {
    expect(resolveEconomicEdgeBarPercent(0, 0.005)).toBeCloseTo(50, 5)
    expect(resolveEconomicEdgeBarPercent(0.005, 0.005)).toBeCloseTo(75, 5)
  })
})
