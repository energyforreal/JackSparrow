import { normalizeConfidenceToPercent } from '@/utils/formatters'
import { resolveDisplayConfidence } from '@/utils/signalConfidence'
import type {
  AgentOverviewInput,
  ConfidencePillarView,
  ConfidenceView,
  QualitativeLevel,
} from './types'

function boolToLevel(passed: boolean | undefined): QualitativeLevel {
  if (passed === true) return 'Excellent'
  if (passed === false) return 'Blocked'
  return 'Unknown'
}

function marketConfidenceToLevel(conf: string | undefined): QualitativeLevel {
  switch (conf?.toLowerCase()) {
    case 'high':
      return 'High'
    case 'medium':
      return 'Medium'
    case 'low':
      return 'Weak'
    default:
      return 'Unknown'
  }
}

function marginToTimingLevel(margin: number | undefined, fsm: string | undefined): QualitativeLevel {
  if (margin == null || !Number.isFinite(margin)) {
    if (fsm === 'EntryReady') return 'High'
    if (fsm === 'SetupForming' || fsm === 'TrendDeveloping') return 'Medium'
    return 'Weak'
  }
  const pct = margin <= 1 ? margin * 100 : margin
  if (pct >= 20) return 'High'
  if (pct >= 12) return 'Good'
  if (pct >= 6) return 'Medium'
  return 'Weak'
}

const COMPONENT_LABELS: Record<string, string> = {
  thesis: 'Thesis',
  ml: 'ML',
  regime_fit: 'Regime',
  liquidity: 'Liquidity',
  structure: 'Structure',
  gates: 'Gates',
  multi_horizon: 'Horizon',
}

export function resolveConfidence(input: AgentOverviewInput): ConfidenceView {
  const { signal } = input
  const aggregate = signal ? resolveDisplayConfidence(signal).percent : 0
  const pillars: ConfidencePillarView[] = []

  if (!signal) {
    return { aggregatePercent: 0, pillars }
  }

  const gates = signal.structural_gates as { categories?: Record<string, boolean> } | undefined
  const cats = gates?.categories ?? {}
  const ms = signal.market_state as Record<string, unknown> | undefined

  pillars.push({
    key: 'trend',
    label: 'Trend',
    level: boolToLevel(cats.trend),
  })
  pillars.push({
    key: 'structure',
    label: 'Structure',
    level: boolToLevel(cats.structure),
  })
  pillars.push({
    key: 'liquidity',
    label: 'Liquidity',
    level: boolToLevel(cats.liquidity),
  })
  pillars.push({
    key: 'timing',
    label: 'Timing',
    level: marginToTimingLevel(
      signal.entry_proba_margin ?? signal.signal_strength,
      signal.fsm_state
    ),
  })

  if (ms?.confidence) {
    pillars.push({
      key: 'market',
      label: 'Market',
      level: marketConfidenceToLevel(String(ms.confidence)),
    })
  }

  return { aggregatePercent: aggregate, pillars }
}

export { COMPONENT_LABELS }
