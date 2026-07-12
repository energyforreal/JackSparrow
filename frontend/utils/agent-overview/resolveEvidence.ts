import { resolveDecisionReasoning, resolveTradeScore } from '@/utils/signalConfidence'
import { normalizeConfidenceToPercent } from '@/utils/formatters'
import { resolveReasonCopy } from './catalogs/reasonCatalog'
import type { AgentOverviewInput, EvidenceRowView, EvidenceView } from './types'

/** Reason-code tokens that indicate adverse / blocking evidence. */
const AGAINST_TOKENS = ['penalty', 'below', 'fail', 'reject', 'blocked', 'insufficient'] as const

export function evidenceReasonStatus(code: string): EvidenceRowView['status'] {
  const lower = String(code).toLowerCase()
  return AGAINST_TOKENS.some((t) => lower.includes(t)) ? 'against' : 'support'
}

export function resolveEvidence(input: AgentOverviewInput): EvidenceView {
  const { signal, modelConsensus } = input
  const rows: EvidenceRowView[] = []

  if (!signal) return { rows }

  const ts = resolveTradeScore(signal)
  if (ts?.reason_codes?.length) {
    for (const code of ts.reason_codes.slice(0, 6)) {
      rows.push({
        key: `reason_${code}`,
        label: resolveReasonCopy(code),
        status: evidenceReasonStatus(code),
      })
    }
  }

  const er = signal.expected_return
  const thr = signal.threshold
  if (er != null && thr != null && Number.isFinite(Number(er)) && Number.isFinite(Number(thr))) {
    const edge = Number(er) - Number(thr)
    rows.push({
      key: 'economics',
      label:
        edge > 0
          ? 'Expected return exceeds threshold'
          : 'Expected return below threshold',
      status: edge > 0 ? 'support' : 'against',
      detail: `Δ ${edge >= 0 ? '+' : ''}${edge.toFixed(5)}`,
    })
  } else if (signal.economic_edge != null) {
    const edge = Number(signal.economic_edge)
    rows.push({
      key: 'economics',
      label: edge > 0 ? 'Positive economic edge' : 'Negative economic edge',
      status: edge > 0 ? 'support' : 'against',
    })
  }

  const consensus = modelConsensus ?? null
  if (consensus && consensus.confidence > 0) {
    const pct = normalizeConfidenceToPercent(consensus.confidence)
    const sig = consensus.signal ? String(consensus.signal) : ''
    const aligns =
      sig &&
      signal.signal &&
      (sig.includes('LONG') === String(signal.signal).includes('LONG') ||
        sig.includes('SHORT') === String(signal.signal).includes('SHORT') ||
        sig === 'HOLD')
    rows.push({
      key: 'ml',
      label: aligns
        ? `ML ensemble supports ${sig.replace('_', ' ')}`
        : `ML ensemble: ${sig || 'mixed'} (${Math.round(pct)}%)`,
      status: aligns ? 'support' : 'neutral',
    })
  }

  const reasoning = resolveDecisionReasoning(signal)
  if (reasoning && reasoning.length > 20) {
    rows.push({
      key: 'reasoning',
      label: 'Reasoning supports assessment',
      status: 'support',
      detail: reasoning.length > 120 ? `${reasoning.slice(0, 117)}…` : reasoning,
    })
  }

  if (signal.v43_gate_reject) {
    rows.push({
      key: 'gate_reject',
      label: resolveReasonCopy(String(signal.v43_gate_reject)),
      status: 'against',
    })
  }

  const policyCodes = signal.policy_reason_codes
  if (Array.isArray(policyCodes)) {
    for (const code of policyCodes.slice(0, 3)) {
      rows.push({
        key: `policy_${code}`,
        label: resolveReasonCopy(String(code)),
        status: 'neutral',
      })
    }
  }

  if (!rows.length) {
    rows.push({
      key: 'pending',
      label: 'Awaiting evidence from next prediction cycle',
      status: 'unknown',
    })
  }

  return { rows }
}
