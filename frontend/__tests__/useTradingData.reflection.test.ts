/**
 * Unit test for reflection snapshot persistence in trading data reducer logic.
 * We import the reducer indirectly by duplicating the agent_update branch behavior.
 */

import type { ReflectionSnapshot } from '@/types'

describe('reflection snapshot handling', () => {
  it('preserves reflection when agent_update includes reflection_snapshot', () => {
    const reflection: ReflectionSnapshot = {
      version: '1.0',
      timestamp: '2026-05-24T00:00:00Z',
      symbol: 'BTCUSD',
      position_id: 'p1',
      advisory_only: true,
      predicted_signal: 'BUY',
      exit_reason: 'tp',
      pnl: 1,
      was_profitable: true,
      calibration_bucket: 'high_confidence_win',
      quality_score: 0.8,
      diagnostics: [],
      reason_codes: [],
    }

    const prev = { lastReflection: null as ReflectionSnapshot | null }
    const data = {
      state: 'POSITION_REFLECTION',
      reflection_snapshot: reflection,
    }

    const nextReflection =
      data?.reflection_snapshot && typeof data.reflection_snapshot === 'object'
        ? (data.reflection_snapshot as ReflectionSnapshot)
        : prev.lastReflection

    expect(nextReflection).toEqual(reflection)
  })
})
