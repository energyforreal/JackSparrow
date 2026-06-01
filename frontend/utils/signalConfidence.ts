import { normalizeConfidenceToPercent } from '@/utils/formatters'

export type ConfidenceSource = 'reasoning' | 'policy'

export interface DisplayConfidenceResult {
  /** Normalized 0–100 value for progress bars and labels. */
  percent: number
  /** Which field supplied the displayed value. */
  source: ConfidenceSource
  /** True when final_confidence was absent and policy confidence was used. */
  usedPolicyFallback: boolean
  /** Optional policy/raw score when reasoning confidence is shown separately. */
  policyPercent?: number
}

type ConfidenceCarrier = {
  confidence?: number | null
  final_confidence?: number | null
  confidence_source?: ConfidenceSource | string | null
}

/**
 * Resolve the confidence shown on the Trading Signal card.
 * Prefers calibrated reasoning confidence when available.
 */
export function resolveDisplayConfidence(
  signal: ConfidenceCarrier | null | undefined
): DisplayConfidenceResult {
  const policyPercent = normalizeConfidenceToPercent(signal?.confidence)
  const finalRaw = signal?.final_confidence
  const hasFinal =
    finalRaw !== null &&
    finalRaw !== undefined &&
    Number.isFinite(Number(finalRaw))

  if (hasFinal) {
    return {
      percent: normalizeConfidenceToPercent(finalRaw),
      source: 'reasoning',
      usedPolicyFallback: false,
      policyPercent,
    }
  }

  const hintedSource = signal?.confidence_source
  const source: ConfidenceSource =
    hintedSource === 'reasoning' ? 'reasoning' : 'policy'

  return {
    percent: policyPercent,
    source,
    usedPolicyFallback: true,
  }
}
