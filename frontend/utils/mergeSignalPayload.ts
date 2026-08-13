import type { ExecutionPlan, Signal, SignalType } from '@/types'
import { AgentIntrospectionSnapshotSchema } from '@/schemas/api.validation'

const ACTIONABLE_SIGNALS = new Set([
  'BUY',
  'SELL',
  'STRONG_BUY',
  'STRONG_SELL',
])

const TRANSFORMER_PLAN_KEYS = [
  'execution_plan',
  'long_edge',
  'short_edge',
  'winning_edge',
  'primary_tf',
  'transformer_vol_regime',
  'decision_path',
  'multi_tf_predictions',
  'cross_tf_summary',
] as const

/** Merge WS signal payloads without retaining omitted confidence keys (BUG 2). */
export function mergeSignalPayload(
  signal: Signal | null,
  data: Record<string, unknown>
): Signal {
  const prev = signal
  const out: Record<string, unknown> = prev
    ? { ...prev }
    : { signal: 'HOLD' as SignalType, confidence: 0 }

  const incomingSignal =
    data.signal != null ? String(data.signal) : undefined
  const isHoldPatch = incomingSignal === 'HOLD'
  const isActionablePatch =
    incomingSignal != null && ACTIONABLE_SIGNALS.has(incomingSignal.toUpperCase())
  const partialHold =
    isHoldPatch &&
    !('confidence' in data) &&
    !('final_confidence' in data) &&
    !('signal_strength' in data)
  const explicitNonActionableHold =
    isHoldPatch &&
    'is_actionable_entry' in data &&
    data.is_actionable_entry !== true &&
    data.is_actionable_entry !== 'true'

  for (const [key, value] of Object.entries(data)) {
    if (
      key === 'confidence' ||
      key === 'final_confidence' ||
      key === 'signal_strength' ||
      key === 'v43_gate_reject' ||
      key === 'execution_plan'
    ) {
      continue
    }
    if (value !== undefined) out[key] = value
  }

  if ('confidence' in data && data.confidence !== undefined) {
    out.confidence = data.confidence
  } else if (explicitNonActionableHold || partialHold) {
    out.confidence = 0
  } else if (!partialHold && prev) {
    out.confidence = prev.confidence
  }

  if ('final_confidence' in data && data.final_confidence !== undefined) {
    out.final_confidence = data.final_confidence
  } else if (explicitNonActionableHold || partialHold) {
    delete out.final_confidence
  } else if (!partialHold && prev?.final_confidence !== undefined) {
    out.final_confidence = prev.final_confidence
  }

  if ('signal_strength' in data && data.signal_strength !== undefined) {
    out.signal_strength = data.signal_strength
  } else if (explicitNonActionableHold || partialHold) {
    delete out.signal_strength
  } else if (!partialHold && prev?.signal_strength !== undefined) {
    out.signal_strength = prev.signal_strength
  }

  if ('server_timestamp_ms' in data && data.server_timestamp_ms !== undefined) {
    out.server_timestamp_ms = data.server_timestamp_ms
  } else if (prev?.server_timestamp_ms !== undefined) {
    out.server_timestamp_ms = prev.server_timestamp_ms
  }

  // Gate reject: update when present; clear on actionable patches that omit it
  // (avoids sticky leftover after transformer_mtf nulls the field).
  if ('v43_gate_reject' in data && data.v43_gate_reject !== undefined) {
    out.v43_gate_reject = data.v43_gate_reject
  } else if (isActionablePatch) {
    delete out.v43_gate_reject
  } else if (prev?.v43_gate_reject !== undefined) {
    out.v43_gate_reject = prev.v43_gate_reject
  }

  if ('execution_plan' in data && data.execution_plan !== undefined) {
    const incoming = data.execution_plan
    if (incoming && typeof incoming === 'object' && !Array.isArray(incoming)) {
      const prevPlan =
        prev?.execution_plan && typeof prev.execution_plan === 'object'
          ? prev.execution_plan
          : {}
      out.execution_plan = {
        ...(prevPlan as ExecutionPlan),
        ...(incoming as ExecutionPlan),
      }
    } else {
      out.execution_plan = incoming
    }
  } else if (prev?.execution_plan !== undefined && !isHoldPatch) {
    out.execution_plan = prev.execution_plan
  } else if (isHoldPatch && !('execution_plan' in data)) {
    // HOLD without a plan: drop stale size/SL from prior entry signal
    delete out.execution_plan
  }

  for (const key of TRANSFORMER_PLAN_KEYS) {
    if (key === 'execution_plan') continue
    if (key in data && data[key] !== undefined) {
      out[key] = data[key]
    } else if (prev && (prev as Record<string, unknown>)[key] !== undefined && !isHoldPatch) {
      out[key] = (prev as Record<string, unknown>)[key]
    }
  }

  if (data.timestamp !== undefined) {
    out.timestamp = data.timestamp as string
  } else {
    // Patch omitted timestamp: stamp merge time so freshness UI reflects last WS update.
    out.timestamp = new Date().toISOString()
  }

  const merged = out as Signal
  const intro = data.agent_introspection
  if (intro && typeof intro === 'object') {
    const parsed = AgentIntrospectionSnapshotSchema.safeParse(intro)
    if (parsed.success) merged.agent_introspection = parsed.data
  }
  return merged
}
