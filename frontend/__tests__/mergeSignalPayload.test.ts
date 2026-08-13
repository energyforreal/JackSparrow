import { mergeSignalPayload } from '@/utils/mergeSignalPayload'
import type { Signal } from '@/types'

describe('mergeSignalPayload', () => {
  it('preserves v43_gate_reject when decision_ready patch omits it', () => {
    const prev: Signal = {
      signal: 'HOLD',
      confidence: 0.4,
      v43_gate_reject: 'path_edge_below_threshold',
    }

    const merged = mergeSignalPayload(prev, {
      signal: 'HOLD',
      confidence: 0.35,
      reasoning_chain: [],
    })

    expect(merged.v43_gate_reject).toBe('path_edge_below_threshold')
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

  it('preserves server_timestamp_ms across partial patches', () => {
    const prev: Signal = {
      signal: 'SELL',
      confidence: 0.8,
      server_timestamp_ms: 1_700_000_000_000,
      timestamp: '2026-06-03T06:00:00.000Z',
    }
    const merged = mergeSignalPayload(prev, { signal: 'HOLD' })
    expect(merged.server_timestamp_ms).toBe(1_700_000_000_000)
  })

  it('clears confidence on partial HOLD patch', () => {
    const prev: Signal = {
      signal: 'SELL',
      confidence: 0.85,
      final_confidence: 0.72,
      signal_strength: 0.6,
    }
    const merged = mergeSignalPayload(prev, { signal: 'HOLD' })
    expect(merged.confidence).toBe(0)
    expect(merged.final_confidence).toBeUndefined()
    expect(merged.signal_strength).toBeUndefined()
  })

  it('clears confidence when HOLD is explicitly non-actionable', () => {
    const prev: Signal = {
      signal: 'SELL',
      confidence: 0.9,
      final_confidence: 0.8,
    }
    const merged = mergeSignalPayload(prev, {
      signal: 'HOLD',
      is_actionable_entry: false,
      confidence: 0.3,
    })
    expect(merged.confidence).toBe(0.3)
    expect(merged.final_confidence).toBeUndefined()
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

  it('clears sticky v43_gate_reject on actionable signal that omits it', () => {
    const prev: Signal = {
      signal: 'HOLD',
      confidence: 0.4,
      v43_gate_reject: 'path_edge_below_threshold',
    }
    const merged = mergeSignalPayload(prev, {
      signal: 'BUY',
      confidence: 0.62,
      is_actionable_entry: true,
    })
    expect(merged.v43_gate_reject).toBeUndefined()
  })

  it('merges execution_plan fields from patch', () => {
    const prev: Signal = {
      signal: 'BUY',
      confidence: 0.5,
      execution_plan: {
        size_scale: 0.5,
        size_fraction: 0.3,
        rr_soft_action: 'none',
      },
    }
    const merged = mergeSignalPayload(prev, {
      signal: 'BUY',
      confidence: 0.55,
      execution_plan: {
        size_scale: 0.7,
        stop_loss_pct: 0.004,
        take_profit_pct: 0.008,
        rr_soft_action: 'reduce_size',
      },
      long_edge: 0.01,
      decision_path: 'transformer_mtf',
    })
    expect(merged.execution_plan?.size_scale).toBe(0.7)
    expect(merged.execution_plan?.size_fraction).toBe(0.3)
    expect(merged.execution_plan?.rr_soft_action).toBe('reduce_size')
    expect(merged.execution_plan?.stop_loss_pct).toBe(0.004)
    expect(merged.long_edge).toBe(0.01)
    expect(merged.decision_path).toBe('transformer_mtf')
  })

  it('drops stale execution_plan on HOLD patch without plan', () => {
    const prev: Signal = {
      signal: 'BUY',
      confidence: 0.7,
      execution_plan: { size_scale: 1, size_fraction: 0.6 },
    }
    const merged = mergeSignalPayload(prev, { signal: 'HOLD', confidence: 0 })
    expect(merged.execution_plan).toBeUndefined()
  })
})
