import { resolveTradeScore } from '@/utils/signalConfidence'
import { TRADE_SCORE_COMPONENT_MAX, type AgentOverviewInput, type ScoreBarView, type ScoreBreakdownView } from './types'

const COMPONENT_LABELS: Record<string, string> = {
  thesis: 'Thesis',
  ml: 'ML',
  regime_fit: 'Regime',
  liquidity: 'Liquidity',
  structure: 'Structure',
  gates: 'Gates',
  multi_horizon: 'Horizon',
}

const ORDER = ['thesis', 'ml', 'liquidity', 'structure', 'gates', 'regime_fit', 'multi_horizon']

export function resolveScoreBreakdown(input: AgentOverviewInput): ScoreBreakdownView {
  const ts = input.signal ? resolveTradeScore(input.signal) : undefined
  if (!ts) {
    return { total: 0, passed: null, bars: [] }
  }

  const components = ts.components ?? {}
  const bars: ScoreBarView[] = []

  for (const key of ORDER) {
    const val = components[key]
    if (val == null) continue
    const max = TRADE_SCORE_COMPONENT_MAX[key] ?? 10
    bars.push({
      key,
      label: COMPONENT_LABELS[key] ?? key,
      value: val,
      max,
      normalizedPercent: Math.min(100, Math.round((val / max) * 100)),
    })
  }

  return {
    total: Math.round(ts.score),
    passed: ts.passed ?? null,
    bars,
  }
}
