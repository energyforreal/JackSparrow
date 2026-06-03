import { normalizeConfidenceToPercent } from '@/utils/formatters'

type SignalWithFreshness = {
  server_timestamp_ms?: number | null
  timestamp?: string | Date | null
}

/**
 * Resolve the best-available epoch ms for signal freshness display.
 * Prefers server_timestamp_ms (wall-clock from agent emit) over timestamp ISO string,
 * mirroring the handler-side age check in decision_payload_age_seconds.
 */
export function resolveSignalFreshnessMs(
  signal: SignalWithFreshness | null | undefined
): number | null {
  if (!signal) return null
  const ms = signal.server_timestamp_ms
  if (ms != null && Number.isFinite(Number(ms)) && Number(ms) > 0) {
    return Number(ms)
  }
  const ts = signal.timestamp
  if (!ts) return null
  const d = new Date(ts as string)
  if (!Number.isNaN(d.getTime()) && d.getUTCFullYear() >= 2000) {
    return d.getTime()
  }
  return null
}

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
  /** Entry-proba margin strength (0–100), when surfaced by agent. */
  signalStrengthPercent?: number
}

type ConfidenceCarrier = {
  confidence?: number | null
  final_confidence?: number | null
  confidence_source?: ConfidenceSource | string | null
  signal_strength?: number | null
  calibrated_confidence?: number | null
  policy_confidence?: number | null
  display_confidence?: number | null
  trade_score?: number | null
  is_actionable_entry?: boolean | null
  agent_introspection?: {
    trade_score?: number | null
    trade_score_pass?: boolean | null
  } | null
}

export interface TradeScoreInfo {
  score: number
  passed?: boolean
}

export interface SignalEntryMetrics {
  reasoningPercent: number
  policyEntryPercent: number
  tradeScore?: TradeScoreInfo
  signalStrengthPercent?: number
  isActionableEntry?: boolean
  showSplitConfidence: boolean
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

  const strengthPercent =
    signal?.signal_strength !== null && signal?.signal_strength !== undefined
      ? normalizeConfidenceToPercent(signal.signal_strength)
      : undefined

  if (hasFinal) {
    return {
      percent: normalizeConfidenceToPercent(finalRaw),
      source: 'reasoning',
      usedPolicyFallback: false,
      policyPercent,
      signalStrengthPercent: strengthPercent,
    }
  }

  const hintedSource = signal?.confidence_source
  const source: ConfidenceSource =
    hintedSource === 'reasoning' ? 'reasoning' : 'policy'

  return {
    percent: policyPercent,
    source,
    usedPolicyFallback: true,
    signalStrengthPercent: strengthPercent,
  }
}

/** Policy/ML confidence used for DecisionReady and entry gating (not reasoning step 7). */
export function resolvePolicyEntryPercent(
  signal: ConfidenceCarrier | null | undefined,
  display?: DisplayConfidenceResult
): number {
  if (!signal) return 0
  if (signal.policy_confidence != null && Number.isFinite(Number(signal.policy_confidence))) {
    return normalizeConfidenceToPercent(signal.policy_confidence)
  }
  const d = display ?? resolveDisplayConfidence(signal)
  if (d.policyPercent != null && Number.isFinite(d.policyPercent)) {
    return d.policyPercent
  }
  return normalizeConfidenceToPercent(signal.confidence)
}

export function resolveTradeScore(
  signal: ConfidenceCarrier | null | undefined
): TradeScoreInfo | undefined {
  if (!signal) return undefined
  const intro = signal.agent_introspection
  const raw = signal.trade_score ?? intro?.trade_score
  if (raw == null || !Number.isFinite(Number(raw))) return undefined
  const passed =
    intro?.trade_score_pass != null ? Boolean(intro.trade_score_pass) : undefined
  return { score: Number(raw), passed }
}

/** Full entry vs display breakdown for the Trading Signal card. */
export function resolveSignalEntryMetrics(
  signal: ConfidenceCarrier | null | undefined
): SignalEntryMetrics | null {
  if (!signal) return null
  const display = resolveDisplayConfidence(signal)
  const policyEntryPercent = resolvePolicyEntryPercent(signal, display)
  const tradeScore = resolveTradeScore(signal)
  const showSplitConfidence =
    display.source === 'reasoning' &&
    Math.abs(policyEntryPercent - display.percent) >= 1
  return {
    reasoningPercent: display.percent,
    policyEntryPercent,
    tradeScore,
    signalStrengthPercent: display.signalStrengthPercent,
    isActionableEntry:
      signal.is_actionable_entry != null
        ? Boolean(signal.is_actionable_entry)
        : undefined,
    showSplitConfidence,
  }
}
