import { describe, expect, it } from '@jest/globals'

import {
  resolveDecisionReasoning,
  resolveSignalFreshnessMs,
} from '@/utils/signalConfidence'

describe('resolveSignalFreshnessMs', () => {
  it('prefers server_timestamp_ms over ISO timestamp', () => {
    const ms = resolveSignalFreshnessMs({
      server_timestamp_ms: 1_700_000_000_000,
      timestamp: '1990-01-01T00:00:00.000Z',
    })
    expect(ms).toBe(1_700_000_000_000)
  })

  it('falls back to timestamp when server_timestamp_ms absent', () => {
    const ms = resolveSignalFreshnessMs({
      timestamp: '2026-06-03T12:00:00.000Z',
    })
    expect(ms).toBe(new Date('2026-06-03T12:00:00.000Z').getTime())
  })

  it('returns null for invalid inputs', () => {
    expect(resolveSignalFreshnessMs(null)).toBeNull()
    expect(resolveSignalFreshnessMs({ timestamp: 'not-a-date' })).toBeNull()
  })
})

describe('resolveDecisionReasoning', () => {
  it('prefers agent_decision_reasoning', () => {
    expect(
      resolveDecisionReasoning({
        agent_decision_reasoning: 'SELL - policy',
        conclusion: 'HOLD - other',
      })
    ).toBe('SELL - policy')
  })

  it('falls back to conclusion', () => {
    expect(
      resolveDecisionReasoning({
        conclusion: 'HOLD - awaiting policy',
      })
    ).toBe('HOLD - awaiting policy')
  })

  it('falls back to reasoning_chain_full.conclusion', () => {
    expect(
      resolveDecisionReasoning({
        reasoning_chain_full: { conclusion: 'BUY - thesis' },
      })
    ).toBe('BUY - thesis')
  })
})
