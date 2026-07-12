import { describe, expect, it } from '@jest/globals'

import {
  evidenceReasonStatus,
  resolveEvidence,
} from '@/utils/agent-overview/resolveEvidence'

describe('evidenceReasonStatus', () => {
  it('marks quality_economic_gate5_fail as against', () => {
    expect(evidenceReasonStatus('quality_economic_gate5_fail')).toBe('against')
  })

  it('marks quality_below_floor as against', () => {
    expect(evidenceReasonStatus('quality_below_floor')).toBe('against')
  })

  it('marks blocked and reject tokens as against', () => {
    expect(evidenceReasonStatus('entry_blocked')).toBe('against')
    expect(evidenceReasonStatus('gate_reject')).toBe('against')
    expect(evidenceReasonStatus('quality_economic_edge_insufficient')).toBe('against')
  })

  it('marks neutral supportive codes as support', () => {
    expect(evidenceReasonStatus('quality_structural_thesis')).toBe('support')
    expect(evidenceReasonStatus('quality_position_clear')).toBe('support')
  })
})

describe('resolveEvidence', () => {
  it('paints gate5 fail reason codes against', () => {
    const view = resolveEvidence({
      signal: {
        trade_score: {
          score: 47,
          passed: false,
          reason_codes: ['quality_economic_gate5_fail', 'quality_structural_thesis'],
        },
      } as never,
      agentState: 'MONITORING',
    })
    const gate5 = view.rows.find((r) => r.key.includes('gate5_fail'))
    const structural = view.rows.find((r) => r.key.includes('structural_thesis'))
    expect(gate5?.status).toBe('against')
    expect(structural?.status).toBe('support')
  })

  it('uses short-aware edge so STRONG SHORT is not always below threshold', () => {
    const view = resolveEvidence({
      signal: {
        signal: 'SHORT',
        expected_return: -0.015,
        threshold: 0.005,
        economic_edge: -0.02,
      } as never,
      agentState: 'MONITORING',
    })
    const economics = view.rows.find((r) => r.key === 'economics')
    expect(economics?.status).toBe('support')
    expect(economics?.label).toContain('exceeds')
    expect(economics?.detail).toContain('(short)')
  })
})
