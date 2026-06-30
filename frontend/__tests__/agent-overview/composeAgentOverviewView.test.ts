import { describe, expect, it } from '@jest/globals'

import { AGENT_OVERVIEW_FIXTURES, LONG_ENTRY_READY, LONG_MANAGING } from '@/fixtures/agentOverviewSignals'
import { composeAgentOverviewView } from '@/utils/agent-overview/composeAgentOverviewView'
import { presentAgentOverview } from '@/utils/agent-overview/agentOverviewPresenter'
import { resolveHero, resolveMode } from '@/utils/agent-overview/resolveHero'
import { resolveReadinessLabel } from '@/utils/agent-overview/resolveReadiness'
import { shouldShowOpsStrip } from '@/utils/agent-overview/resolveOpsContext'

describe('composeAgentOverviewView', () => {
  it('composes all fixtures without throwing', () => {
    for (const fx of AGENT_OVERVIEW_FIXTURES) {
      const view = composeAgentOverviewView({
        signal: fx.signal,
        agentState: fx.agentState,
        health: fx.health,
      })
      expect(view.hero.direction).toBeTruthy()
      expect(view.readiness.label).toBeTruthy()
      const presented = presentAgentOverview(view)
      expect(presented.hero.directionLabel).toBeTruthy()
    }
  })

  it('entry ready maps to Ready readiness and shows ops', () => {
    const view = composeAgentOverviewView({
      signal: LONG_ENTRY_READY.signal,
      agentState: LONG_ENTRY_READY.agentState,
      health: LONG_ENTRY_READY.health,
    })
    expect(view.readiness.label).toBe('Ready')
    expect(view.ops.show).toBe(true)
    expect(view.showEntrySections).toBe(true)
  })

  it('managing mode morphs sections', () => {
    const view = composeAgentOverviewView({
      signal: LONG_MANAGING.signal,
      agentState: LONG_MANAGING.agentState,
      health: LONG_MANAGING.health,
    })
    expect(resolveMode(LONG_MANAGING.signal)).toBe('managing')
    expect(view.showManagingSections).toBe(true)
    expect(shouldShowOpsStrip({
      signal: LONG_MANAGING.signal,
      agentState: LONG_MANAGING.agentState,
    })).toBe(true)
  })

  it('gates and evidence are distinct', () => {
    const view = composeAgentOverviewView({
      signal: LONG_ENTRY_READY.signal,
      agentState: LONG_ENTRY_READY.agentState,
    })
    const gateLabels = new Set(view.gates.rows.map((r) => r.label))
    const evidenceHasMl = view.evidence.rows.some((r) => r.key === 'ml' || r.label.includes('ML'))
    expect(gateLabels.has('Liquidity')).toBe(true)
    expect(gateLabels.has('Trend')).toBe(true)
    expect(view.evidence.rows.length).toBeGreaterThan(0)
  })
})

describe('resolveHero priority', () => {
  it('prefers lifecycle over raw signal for managing', () => {
    const hero = resolveHero({
      signal: LONG_MANAGING.signal,
      agentState: 'MONITORING_POSITION',
    })
    expect(hero.lifecycleLabel.toLowerCase()).toContain('managing')
  })
})

describe('resolveReadinessLabel', () => {
  it('returns Blocked for gate fail fixture', () => {
    const fx = AGENT_OVERVIEW_FIXTURES.find((f) => f.id === 'BLOCKED_GATE_FAIL')!
    expect(
      resolveReadinessLabel({ signal: fx.signal, agentState: fx.agentState })
    ).toBe('Blocked')
  })
})

describe('presenter performance smoke', () => {
  it('completes compose + present quickly on fixtures', () => {
    const start = performance.now()
    for (let i = 0; i < 100; i++) {
      for (const fx of AGENT_OVERVIEW_FIXTURES) {
        presentAgentOverview(
          composeAgentOverviewView({
            signal: fx.signal,
            agentState: fx.agentState,
            health: fx.health,
          })
        )
      }
    }
    const elapsed = performance.now() - start
    expect(elapsed).toBeLessThan(500)
  })
})
