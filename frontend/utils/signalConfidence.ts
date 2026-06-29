import { normalizeConfidenceToPercent } from '@/utils/formatters'
import type { TradeScoreDetail } from '@/types'

type SignalWithFreshness = {
  server_timestamp_ms?: number | null
  timestamp?: string | Date | null
}

/**
 * Resolve the best-available epoch ms for signal freshness display.
 * Prefers server_timestamp_ms (wall-clock from agent emit) over timestamp ISO string,
 * mirroring the handler-side age check in decision_payload_age_seconds.
 */
type DecisionReasoningCarrier = {
  agent_decision_reasoning?: string | null
  conclusion?: string | null
  reasoning_chain_full?: { conclusion?: string | null } | null
}

/** Decision text for UI: backend field, then conclusion aliases. */
export function resolveDecisionReasoning(
  signal: DecisionReasoningCarrier | null | undefined
): string | undefined {
  if (!signal) return undefined
  const direct = signal.agent_decision_reasoning?.trim()
  if (direct) return direct
  const top = signal.conclusion?.trim()
  if (top) return top
  const chain = signal.reasoning_chain_full?.conclusion?.trim()
  return chain || undefined
}

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

type TradeScoreRaw =
  | number
  | TradeScoreDetail
  | {
      score?: number | null
      passed?: boolean | null
      components?: Record<string, number>
      reason_codes?: string[]
    }
  | null
  | undefined

type ConfidenceCarrier = {
  confidence?: number | null
  final_confidence?: number | null
  confidence_source?: ConfidenceSource | string | null
  signal_strength?: number | null
  calibrated_confidence?: number | null
  policy_confidence?: number | null
  display_confidence?: number | null
  trade_score?: TradeScoreRaw
  trade_score_detail?: TradeScoreDetail | null
  economic_edge?: number | null
  entry_proba_margin?: number | null
  reasoning_confidence_raw?: number | null
  threshold?: number | null
  expected_return?: number | null
  is_actionable_entry?: boolean | null
  signal?: string | null
  agent_introspection?: {
    trade_score?: number | null
    trade_score_pass?: boolean | null
  } | null
  market_context_excerpt?: {
    trade_score?: TradeScoreDetail | number | null
    ml_validation?: {
      expected_return?: number
      threshold?: number
      short_threshold?: number
    }
  } | null
}

export interface TradeScoreInfo {
  score: number
  passed?: boolean
  components?: Record<string, number>
  reason_codes?: string[]
}

export interface HeroMetrics {
  policyEntryPercent: number
  economicEdge?: number
  economicEdgeBarPercent?: number
  entryMarginPercent?: number
  tradeScore?: TradeScoreInfo
  reasoningPercent?: number
  reasoningRawPercent?: number
  holdDim: boolean
  showSplitConfidence: boolean
  policyReasoningDelta?: number
}

export interface SignalEntryMetrics {
  reasoningPercent: number
  policyEntryPercent: number
  tradeScore?: TradeScoreInfo
  signalStrengthPercent?: number
  isActionableEntry?: boolean
  showSplitConfidence: boolean
  /** Policy minus reasoning (percentage points), when both are defined. */
  policyReasoningDelta?: number
  holdDim: boolean
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

function parseTradeScoreRaw(
  raw: TradeScoreRaw
): { score: number; passed?: boolean; components?: Record<string, number>; reason_codes?: string[] } | undefined {
  if (raw == null) return undefined
  if (typeof raw === 'object' && !Array.isArray(raw)) {
    const score = raw.score
    if (score == null || !Number.isFinite(Number(score))) return undefined
    const passed =
      raw.passed != null && raw.passed !== undefined ? Boolean(raw.passed) : undefined
    const components =
      raw.components && typeof raw.components === 'object' ? raw.components : undefined
    const reason_codes = Array.isArray(raw.reason_codes) ? raw.reason_codes : undefined
    return { score: Number(score), passed, components, reason_codes }
  }
  if (!Number.isFinite(Number(raw))) return undefined
  return { score: Number(raw) }
}

function resolveEconomicEdgeValue(signal: ConfidenceCarrier): number | undefined {
  if (signal.economic_edge != null && Number.isFinite(Number(signal.economic_edge))) {
    return Number(signal.economic_edge)
  }
  const er = signal.expected_return
  const thr = signal.threshold
  if (er != null && thr != null && Number.isFinite(Number(er)) && Number.isFinite(Number(thr))) {
    return Number(er) - Number(thr)
  }
  const ml = signal.market_context_excerpt?.ml_validation
  if (ml?.expected_return != null && ml?.threshold != null) {
    try {
      return Number(ml.expected_return) - Number(ml.threshold)
    } catch {
      return undefined
    }
  }
  return undefined
}

/** Map signed economic edge to 0–100 bar (50 = at threshold). */
export function resolveEconomicEdgeBarPercent(
  edge: number,
  threshold: number | undefined | null
): number {
  if (!Number.isFinite(edge)) return 50
  const thr =
    threshold != null && Number.isFinite(Number(threshold)) && Number(threshold) > 0
      ? Number(threshold)
      : 0.005
  const ratio = edge / thr
  return Math.max(0, Math.min(100, 50 + ratio * 25))
}

export function resolveEntryMarginPercent(
  signal: ConfidenceCarrier | null | undefined
): number | undefined {
  if (!signal) return undefined
  if (signal.entry_proba_margin != null && Number.isFinite(Number(signal.entry_proba_margin))) {
    return normalizeConfidenceToPercent(signal.entry_proba_margin)
  }
  if (signal.signal_strength != null && Number.isFinite(Number(signal.signal_strength))) {
    return normalizeConfidenceToPercent(signal.signal_strength)
  }
  return undefined
}

/** Four orthogonal hero metrics for the Trading Signal card. */
export function resolveHeroMetrics(
  signal: ConfidenceCarrier | null | undefined
): HeroMetrics | null {
  if (!signal) return null
  const entry = resolveSignalEntryMetrics(signal)
  if (!entry) return null

  const economicEdge = resolveEconomicEdgeValue(signal)
  const entryMarginPercent = resolveEntryMarginPercent(signal)
  const tradeFromDetail = parseTradeScoreRaw(signal.trade_score_detail)
  const tradeScore = tradeFromDetail
    ? {
        score: tradeFromDetail.score,
        passed: tradeFromDetail.passed ?? entry.tradeScore?.passed,
        components: tradeFromDetail.components,
        reason_codes: tradeFromDetail.reason_codes,
      }
    : entry.tradeScore

  let reasoningRawPercent: number | undefined
  if (
    signal.reasoning_confidence_raw != null &&
    Number.isFinite(Number(signal.reasoning_confidence_raw))
  ) {
    reasoningRawPercent = normalizeConfidenceToPercent(signal.reasoning_confidence_raw)
  }

  return {
    policyEntryPercent: entry.policyEntryPercent,
    economicEdge,
    economicEdgeBarPercent:
      economicEdge != null
        ? resolveEconomicEdgeBarPercent(economicEdge, signal.threshold)
        : undefined,
    entryMarginPercent,
    tradeScore,
    reasoningPercent: entry.reasoningPercent,
    reasoningRawPercent,
    holdDim: entry.holdDim,
    showSplitConfidence: entry.showSplitConfidence,
    policyReasoningDelta: entry.policyReasoningDelta,
  }
}

export function resolveTradeScore(
  signal: ConfidenceCarrier | null | undefined
): TradeScoreInfo | undefined {
  if (!signal) return undefined
  const intro = signal.agent_introspection
  const excerptTs = signal.market_context_excerpt?.trade_score
  const parsed =
    parseTradeScoreRaw(signal.trade_score_detail) ??
    parseTradeScoreRaw(signal.trade_score) ??
    parseTradeScoreRaw(excerptTs) ??
    parseTradeScoreRaw(intro?.trade_score)
  if (!parsed) return undefined
  const passed =
    parsed.passed ??
    (intro?.trade_score_pass != null ? Boolean(intro.trade_score_pass) : undefined)
  return {
    score: parsed.score,
    passed,
    components: parsed.components,
    reason_codes: parsed.reason_codes,
  }
}

/** True when UI should de-emphasize confidence bars (non-entry HOLD). */
export function isHoldNonActionableDisplay(
  signal: ConfidenceCarrier | null | undefined
): boolean {
  if (!signal) return false
  if (String(signal.signal || '').toUpperCase() !== 'HOLD') return false
  return signal.is_actionable_entry !== true
}

/** Full entry vs display breakdown for the Trading Signal card. */
export function resolveSignalEntryMetrics(
  signal: ConfidenceCarrier | null | undefined
): SignalEntryMetrics | null {
  if (!signal) return null
  const holdDim = isHoldNonActionableDisplay(signal)
  const display = resolveDisplayConfidence(signal)
  const policyEntryPercent = resolvePolicyEntryPercent(signal, display)
  const reasoningPercent = display.percent
  const tradeScore = resolveTradeScore(signal)
  const policyReasoningDelta = policyEntryPercent - reasoningPercent
  const showSplitConfidence =
    display.source === 'reasoning' &&
    Math.abs(policyReasoningDelta) >= 1
  return {
    reasoningPercent,
    policyEntryPercent,
    tradeScore,
    signalStrengthPercent: display.signalStrengthPercent,
    isActionableEntry:
      signal.is_actionable_entry != null
        ? Boolean(signal.is_actionable_entry)
        : undefined,
    showSplitConfidence,
    policyReasoningDelta,
    holdDim,
  }
}
