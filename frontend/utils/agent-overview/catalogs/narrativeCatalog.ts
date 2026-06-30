import type { Signal } from '@/types'
import type { ReadinessLabel } from '../types'

export function synthesizeNarrative(signal: Signal, readinessLabel: ReadinessLabel): string {
  const parts: string[] = []
  const ms = signal.market_state as Record<string, unknown> | undefined
  const trend = ms?.trend ? String(ms.trend) : null
  const liquidity = ms?.liquidity ? String(ms.liquidity) : null

  if (trend === 'bullish') {
    parts.push('Trend remains constructive.')
  } else if (trend === 'bearish') {
    parts.push('Trend remains bearish.')
  } else if (trend === 'neutral') {
    parts.push('Market remains range-bound.')
  }

  if (liquidity === 'healthy') {
    parts.push('Liquidity remains favorable.')
  } else if (liquidity === 'thin' || liquidity === 'stressed') {
    parts.push('Liquidity is constrained.')
  }

  if (signal.economic_edge != null && signal.threshold != null) {
    const edge = Number(signal.economic_edge)
    const thr = Number(signal.threshold)
    if (Number.isFinite(edge) && Number.isFinite(thr)) {
      if (edge > 0) {
        parts.push('Expected return exceeds execution threshold.')
      } else {
        parts.push('Expected return has not cleared the execution threshold.')
      }
    }
  }

  if (readinessLabel === 'SetupForming') {
    parts.push('Setup is forming — waiting for confirmation.')
  } else if (readinessLabel === 'Ready') {
    parts.push('Entry conditions are met; monitoring execution timing.')
  } else if (readinessLabel === 'Managing') {
    parts.push('Managing open position and monitoring thesis health.')
  } else if (readinessLabel === 'ExitReady') {
    parts.push('Evaluating exit conditions.')
  } else if (readinessLabel === 'Blocked') {
    parts.push('Trade blocked by structural or policy constraints.')
  } else if (readinessLabel === 'Observing') {
    parts.push('Observing market — no entry imminent.')
  }

  if (signal.entry_proba_margin != null) {
    const margin = Number(signal.entry_proba_margin)
    if (Number.isFinite(margin) && margin < 0.15) {
      parts.push('Probability separation remains insufficient for entry.')
    }
  }

  return parts.length > 0 ? parts.join(' ') : 'Awaiting next assessment cycle.'
}

export function looksLikeProse(text: string): boolean {
  const t = text.trim()
  if (t.length < 40) return false
  if (/score=\d|thesis=|final_long=/i.test(t)) return false
  return true
}
