import { describe, expect, it } from '@jest/globals'
import { render, screen } from '@testing-library/react'

import { LONG_ENTRY_READY, HOLD_OBSERVING } from '@/fixtures/agentOverviewSignals'
import { AgentOverviewCard } from '@/app/components/agent-overview/AgentOverviewCard'

describe('AgentOverviewCard', () => {
  it('renders entry ready hero', () => {
    render(
      <AgentOverviewCard
        signal={LONG_ENTRY_READY.signal}
        agentState={LONG_ENTRY_READY.agentState}
        health={LONG_ENTRY_READY.health}
        isConnected
      />
    )
    expect(screen.getByText('LONG')).toBeTruthy()
    expect(screen.getByText('Agent Assessment')).toBeTruthy()
    expect(screen.getByText('Decision Gates')).toBeTruthy()
  })

  it('renders empty state without signal', () => {
    render(<AgentOverviewCard signal={null} agentState="OBSERVING" isConnected />)
    expect(screen.getByText(/No signal available/i)).toBeTruthy()
  })

  it('renders hold observing readiness', () => {
    render(
      <AgentOverviewCard
        signal={HOLD_OBSERVING.signal}
        agentState={HOLD_OBSERVING.agentState}
        isConnected
      />
    )
    expect(screen.getByText('HOLD')).toBeTruthy()
  })
})
