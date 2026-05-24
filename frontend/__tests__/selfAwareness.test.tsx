import { render, screen } from '@testing-library/react'
import { SelfAwarenessPanel } from '@/app/components/SelfAwarenessPanel'
import type { AgentIntrospectionSnapshot, ReflectionSnapshot } from '@/types'

const introspection: AgentIntrospectionSnapshot = {
  version: '1.0',
  timestamp: '2026-05-24T00:00:00Z',
  symbol: 'BTCUSD',
  agent_state: 'OBSERVING',
  policy_mode: 'ml_and_thesis',
  policy_signal: 'BUY',
  policy_confidence: 0.72,
  policy_reason_codes: ['signal_buy'],
  memory_enabled: true,
  memory_context_count: 3,
  trade_score: 75,
  trade_score_pass: true,
}

const reflection: ReflectionSnapshot = {
  version: '1.0',
  timestamp: '2026-05-24T01:00:00Z',
  symbol: 'BTCUSD',
  position_id: 'pos_1',
  advisory_only: true,
  predicted_signal: 'BUY',
  exit_reason: 'take_profit',
  pnl: 42.5,
  was_profitable: true,
  direction_correct: true,
  calibration_bucket: 'high_confidence_win',
  quality_score: 0.85,
  diagnostics: [],
  reason_codes: ['direction_aligned_with_pnl'],
}

describe('SelfAwarenessPanel', () => {
  it('renders introspection and reflection sections', () => {
    render(<SelfAwarenessPanel introspection={introspection} reflection={reflection} />)
    expect(screen.getByText('Self-Awareness')).toBeInTheDocument()
    expect(screen.getByText('Decision introspection')).toBeInTheDocument()
    expect(screen.getByText('Post-trade reflection')).toBeInTheDocument()
    expect(screen.getByText('advisory only')).toBeInTheDocument()
    expect(screen.getByText(/Reason codes \(1\)/)).toBeInTheDocument()
  })

  it('returns null when no data provided', () => {
    const { container } = render(<SelfAwarenessPanel />)
    expect(container.firstChild).toBeNull()
  })
})
