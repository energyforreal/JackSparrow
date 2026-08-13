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
  | {
      score?: number | null
      passed?: boolean | null
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
  is_actionable_entry?: boolean | null
  signal?: string | null
  agent_introspection?: {
    trade_score?: number | null
    trade_score_pass?: boolean | null
    policy_mode?: string | null
    policy_reason_codes?: string[] | null
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

function parseTradeScoreRaw(raw: TradeScoreRaw): { score: number; passed?: boolean } | undefined {
  if (raw == null) return undefined
  if (typeof raw === 'object' && !Array.isArray(raw)) {
    const score = raw.score
    if (score == null || !Number.isFinite(Number(score))) return undefined
    const passed =
      raw.passed != null && raw.passed !== undefined ? Boolean(raw.passed) : undefined
    return { score: Number(score), passed }
  }
  if (!Number.isFinite(Number(raw))) return undefined
  return { score: Number(raw) }
}

export function resolveTradeScore(
  signal: ConfidenceCarrier | null | undefined
): TradeScoreInfo | undefined {
  if (!signal) return undefined
  const intro = signal.agent_introspection
  const parsed =
    parseTradeScoreRaw(signal.trade_score) ?? parseTradeScoreRaw(intro?.trade_score)
  if (!parsed) return undefined
  const passed =
    parsed.passed ??
    (intro?.trade_score_pass != null ? Boolean(intro.trade_score_pass) : undefined)
  return { score: parsed.score, passed }
}

/** True when UI should de-emphasize confidence bars (non-entry HOLD). */
export function isHoldNonActionableDisplay(
  signal: ConfidenceCarrier | null | undefined
): boolean {
  if (!signal) return false
  if (String(signal.signal || '').toUpperCase() !== 'HOLD') return false
  return signal.is_actionable_entry !== true
}

export type ConfidenceBand = 'hold' | 'reduced' | 'full'

export interface ConfidenceBandResult {
  band: ConfidenceBand
  label: string
  sizeScale?: number
  sizeFraction?: number
  rrSoftAction?: string
}

type PlanCarrier = ConfidenceCarrier & {
  decision_path?: string | null
  execution_plan?: {
    size_scale?: number | null
    size_fraction?: number | null
    rr_soft_action?: string | null
    reason_codes?: string[] | null
    threshold?: number | null
    long_edge?: number | null
    short_edge?: number | null
    winning_edge?: number | null
    stop_loss_pct?: number | null
    take_profit_pct?: number | null
    favorable_pct?: number | null
    adverse_pct?: number | null
  } | null
  long_edge?: number | null
  short_edge?: number | null
  winning_edge?: number | null
  threshold?: number | null
  policy_reason_codes?: string[] | null
  thesis_signal?: string | null
}

const HOLD_FLOOR = 0.4
const FULL_FLOOR = 0.55

/**
 * Resolve soft confidence band for transformer_mtf (0.40 HOLD / 0.40–0.55 reduced / ≥0.55 full).
 * Prefers execution_plan.size_scale when present.
 */
export function resolveConfidenceBand(
  signal: PlanCarrier | null | undefined,
  holdFloor = HOLD_FLOOR,
  fullFloor = FULL_FLOOR
): ConfidenceBandResult {
  if (!signal) {
    return { band: 'hold', label: 'HOLD band' }
  }
  const sig = String(signal.signal || '').toUpperCase()
  const plan = signal.execution_plan
  const sizeScale =
    plan?.size_scale != null && Number.isFinite(Number(plan.size_scale))
      ? Number(plan.size_scale)
      : undefined
  const sizeFraction =
    plan?.size_fraction != null && Number.isFinite(Number(plan.size_fraction))
      ? Number(plan.size_fraction)
      : undefined
  const rrSoftAction =
    plan?.rr_soft_action && plan.rr_soft_action !== 'none'
      ? String(plan.rr_soft_action)
      : undefined

  if (sig === 'HOLD' || signal.is_actionable_entry === false) {
    return {
      band: 'hold',
      label: 'Below hold floor / no entry',
      sizeScale: 0,
      sizeFraction: 0,
      rrSoftAction,
    }
  }

  if (sizeScale != null) {
    if (sizeScale < 0.999) {
      return {
        band: 'reduced',
        label: 'Reduced size',
        sizeScale,
        sizeFraction,
        rrSoftAction,
      }
    }
    return {
      band: 'full',
      label: 'Full size',
      sizeScale,
      sizeFraction,
      rrSoftAction,
    }
  }

  const policy01 = resolvePolicyEntryPercent(signal) / 100
  if (policy01 < holdFloor) {
    return { band: 'hold', label: 'Below hold floor', sizeScale: 0, sizeFraction: 0 }
  }
  if (policy01 < fullFloor) {
    return {
      band: 'reduced',
      label: 'Reduced-size band',
      sizeScale,
      sizeFraction,
      rrSoftAction,
    }
  }
  return {
    band: 'full',
    label: 'Full-size band',
    sizeScale,
    sizeFraction,
    rrSoftAction,
  }
}

/** True when thesis / trade-score UI slots should be hidden (transformer_mtf path). */
export function isTransformerMtfPath(
  signal: PlanCarrier | null | undefined
): boolean {
  if (!signal) return false
  if (signal.decision_path === 'transformer_mtf') return true
  const mode = signal.agent_introspection?.policy_mode
  return mode === 'transformer_mtf'
}

export function resolveReasonCodes(
  signal: PlanCarrier | null | undefined,
  limit = 6
): string[] {
  if (!signal) return []
  const fromPlan = signal.execution_plan?.reason_codes
  const fromPolicy = signal.policy_reason_codes
  const fromIntro = signal.agent_introspection?.policy_reason_codes
  const codes = (fromPlan?.length ? fromPlan : fromPolicy?.length ? fromPolicy : fromIntro) ?? []
  return codes.filter(Boolean).slice(0, limit)
}

/** Full entry vs display breakdown for the Trading Signal card. */
export function resolveSignalEntryMetrics(
  signal: ConfidenceCarrier | null | undefined
): SignalEntryMetrics | null {
  if (!signal) return null
  const holdDim = isHoldNonActionableDisplay(signal)
  const display = resolveDisplayConfidence(signal)
  let policyEntryPercent = resolvePolicyEntryPercent(signal, display)
  let reasoningPercent = display.percent
  if (holdDim) {
    policyEntryPercent = 0
    reasoningPercent = 0
  }
  const tradeScore = isTransformerMtfPath(signal as PlanCarrier)
    ? undefined
    : resolveTradeScore(signal)
  const showSplitConfidence =
    !holdDim &&
    display.source === 'reasoning' &&
    Math.abs(policyEntryPercent - display.percent) >= 1
  return {
    reasoningPercent,
    policyEntryPercent,
    tradeScore,
    signalStrengthPercent: holdDim ? undefined : display.signalStrengthPercent,
    isActionableEntry:
      signal.is_actionable_entry != null
        ? Boolean(signal.is_actionable_entry)
        : undefined,
    showSplitConfidence,
  }
}
