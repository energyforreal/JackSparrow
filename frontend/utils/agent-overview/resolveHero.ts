import { normalizeSignalType } from '@/types/enums'
import {
  resolveDisplayConfidence,
  resolveSignalFreshnessMs,
  resolveTradeScore,
} from '@/utils/signalConfidence'
import type { AgentOverviewInput, AgentOverviewMode, HeroView } from './types'

const RUNTIME_OPS_STATES = new Set(['EXECUTING', 'EMERGENCY_STOP', 'THINKING', 'DELIBERATING'])

function lifecycleLabel(lifecycle: string | undefined): string {
  if (!lifecycle) return ''
  return lifecycle.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function fsmLabel(fsm: string | undefined): string {
  if (!fsm) return ''
  return fsm.replace(/([A-Z])/g, ' $1').trim()
}

export function resolveMode(signal: AgentOverviewInput['signal']): AgentOverviewMode {
  if (!signal) return 'flat'
  const lc = String(signal.position_lifecycle || '').toLowerCase()
  if (lc === 'managing' || lc === 'exit_ready') return 'managing'
  const fsm = String(signal.fsm_state || '')
  if (fsm === 'Managing' || fsm === 'ExitReady' || fsm === 'PositionActive') return 'managing'
  const dir = normalizeSignalType(signal.signal)
  if (!dir || dir === 'HOLD') {
    const entry = signal.is_actionable_entry
    if (entry) return 'entry'
    return 'flat'
  }
  return 'entry'
}

export function resolveHero(input: AgentOverviewInput): HeroView {
  const { signal, agentState } = input
  const empty: HeroView = {
    direction: 'HOLD',
    directionLabel: 'HOLD',
    lifecycleLabel: 'Observing',
    fsmLabel: '',
    runtimeLabel: null,
    tradeScore: null,
    tradeScorePassed: null,
    confidencePercent: 0,
    confidenceSource: 'policy',
    freshnessMs: null,
    regime: null,
  }
  if (!signal) return empty

  const canon = normalizeSignalType(signal.signal) ?? 'HOLD'
  const display = resolveDisplayConfidence(signal)
  const ts = resolveTradeScore(signal)
  const lc = lifecycleLabel(signal.position_lifecycle)
  const fsm = fsmLabel(signal.fsm_state)

  let primaryLifecycle = lc
  if (!primaryLifecycle && fsm) primaryLifecycle = fsm
  if (!primaryLifecycle) primaryLifecycle = 'Observing'

  const runtimeLabel = RUNTIME_OPS_STATES.has(agentState) ? agentState.replace(/_/g, ' ') : null

  return {
    direction: canon,
    directionLabel: canon.replace('_', ' '),
    lifecycleLabel: primaryLifecycle,
    fsmLabel: fsm,
    runtimeLabel,
    tradeScore: ts?.score ?? null,
    tradeScorePassed: ts?.passed ?? null,
    confidencePercent: display.percent,
    confidenceSource: display.source,
    freshnessMs: resolveSignalFreshnessMs(signal),
    regime: signal.regime ?? null,
  }
}
