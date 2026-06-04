import type { Signal, SignalType } from '@/types'
import { AgentIntrospectionSnapshotSchema } from '@/schemas/api.validation'

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
      key === 'signal_strength'
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

  if ('v43_gate_reject' in data && data.v43_gate_reject !== undefined) {
    out.v43_gate_reject = data.v43_gate_reject
  } else if (prev?.v43_gate_reject !== undefined) {
    out.v43_gate_reject = prev.v43_gate_reject
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
