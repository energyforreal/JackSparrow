import { resolveReasonCopy } from './catalogs/reasonCatalog'
import {
  resolveHeroMetrics,
  resolvePolicyEntryPercent,
} from '@/utils/signalConfidence'
import type { AgentOverviewInput, ReadinessLabel, ReadinessView } from './types'

export function resolveReadinessLabel(
  input: AgentOverviewInput
): ReadinessLabel {
  const { signal, agentState } = input
  if (!signal) return 'Observing'

  const guard = signal.agent_introspection?.portfolio_guard_action
  if (guard && guard !== 'allow' && guard !== 'approved') return 'Blocked'

  if (signal.v43_gate_reject) {
    const gates = signal.structural_gates as { trade_allowed?: boolean } | undefined
    if (gates && gates.trade_allowed === false) return 'Blocked'
  }

  if (agentState === 'EXECUTING' || agentState === 'TRADING') return 'Executing'

  const lc = String(signal.position_lifecycle || '').toLowerCase()
  if (lc === 'managing') return 'Managing'
  if (lc === 'exit_ready') return 'ExitReady'

  const fsm = String(signal.fsm_state || '')
  if (fsm === 'Managing' || fsm === 'PositionActive') return 'Managing'
  if (fsm === 'ExitReady') return 'ExitReady'
  if (fsm === 'EntryReady' && signal.is_actionable_entry) return 'Ready'
  if (fsm === 'SetupForming' || fsm === 'TrendDeveloping') return 'SetupForming'

  const gates = signal.structural_gates as { trade_allowed?: boolean } | undefined
  if (gates?.trade_allowed === false) return 'Blocked'

  return 'Observing'
}

export function resolveReadiness(input: AgentOverviewInput): ReadinessView {
  const { signal } = input
  const label = resolveReadinessLabel(input)
  const subMetrics: ReadinessView['subMetrics'] = []

  if (!signal) {
    return { label, blockedReason: null, subMetrics }
  }

  const hero = resolveHeroMetrics(signal)
  if (hero?.economicEdge != null) {
    subMetrics.push({
      key: 'edge',
      label: 'Economic edge',
      value: `${hero.economicEdge >= 0 ? '+' : ''}${hero.economicEdge.toFixed(5)}`,
    })
  }
  if (hero?.entryMarginPercent != null) {
    subMetrics.push({
      key: 'margin',
      label: 'Entry margin',
      value: `${Math.round(hero.entryMarginPercent)}%`,
      numericPercent: hero.entryMarginPercent,
    })
  }
  const policy = resolvePolicyEntryPercent(signal)
  subMetrics.push({
    key: 'policy',
    label: 'Policy confidence',
    value: `${Math.round(policy)}%`,
    numericPercent: policy,
  })

  const guard = signal.agent_introspection?.portfolio_guard_action
  if (guard) {
    subMetrics.push({
      key: 'risk',
      label: 'Risk approval',
      value: guard === 'allow' || guard === 'approved' ? 'Approved' : guard,
    })
  }

  let blockedReason: string | null = null
  if (label === 'Blocked') {
    blockedReason =
      signal.v43_gate_reject != null
        ? resolveReasonCopy(String(signal.v43_gate_reject))
        : 'Structural or policy constraints block entry'
  }

  return { label, blockedReason, subMetrics }
}
