import { mergeSignalPayload } from '@/utils/mergeSignalPayload'
import type { Signal } from '@/types'

describe('mergeSignalPayload', () => {
  it('preserves v43_gate_reject when decision_ready patch omits it', () => {
    const prev: Signal = {
      signal: 'HOLD',
      confidence: 0.4,
      v43_gate_reject: 'expected_return_below_threshold',
    }

    const merged = mergeSignalPayload(prev, {
      signal: 'HOLD',
      confidence: 0.35,
      reasoning_chain: [],
    })

    expect(merged.v43_gate_reject).toBe('expected_return_below_threshold')
  })

  it('stamps merge time when patch omits timestamp', () => {
    const prev: Signal = {
      signal: 'SELL',
      confidence: 0.8,
      timestamp: '2026-04-12T10:00:00.000Z',
    }
    const before = Date.now()
    const merged = mergeSignalPayload(prev, { signal: 'HOLD' })
    const after = Date.now()
    expect(merged.timestamp).toBeDefined()
    const ts = new Date(String(merged.timestamp)).getTime()
    expect(ts).toBeGreaterThanOrEqual(before - 1000)
    expect(ts).toBeLessThanOrEqual(after + 1000)
    expect(merged.timestamp).not.toBe(prev.timestamp)
  })

  it('uses server timestamp when patch includes it', () => {
    const prev: Signal = { signal: 'HOLD', confidence: 0.3 }
    const merged = mergeSignalPayload(prev, {
      signal: 'HOLD',
      timestamp: '2026-06-03T06:00:00.000Z',
    })
    expect(merged.timestamp).toBe('2026-06-03T06:00:00.000Z')
  })

  it('updates v43_gate_reject when incoming patch includes it', () => {
    const prev: Signal = {
      signal: 'HOLD',
      confidence: 0.4,
      v43_gate_reject: 'old_reason',
    }

    const merged = mergeSignalPayload(prev, {
      signal: 'HOLD',
      v43_gate_reject: 'regime_unfavorable',
    })

    expect(merged.v43_gate_reject).toBe('regime_unfavorable')
  })
})
