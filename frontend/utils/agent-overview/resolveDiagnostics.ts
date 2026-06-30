import { formatConfidence } from '@/utils/formatters'
import type { AgentOverviewInput, DiagnosticsView } from './types'

export function resolveDiagnostics(input: AgentOverviewInput): DiagnosticsView {
  const { signal, modelConsensus } = input
  if (!signal) {
    return {
      hasContent: false,
      hypotheses: [],
      agentContext: null,
      modelConsensus: null,
      reflection: null,
      hasReasoningChain: false,
    }
  }

  const hypotheses: string[] = []
  const hypSnap = signal.hypothesis_snapshot
  const top =
    hypSnap?.hypotheses?.slice(0, 3) ?? signal.agent_introspection?.hypothesis_top ?? []
  for (const h of top) {
    const conf =
      (h.weighted_confidence ?? h.confidence) <= 1
        ? (h.weighted_confidence ?? h.confidence) * 100
        : (h.weighted_confidence ?? h.confidence)
    hypotheses.push(`${h.id} · ${h.direction} · ${formatConfidence(conf)}`)
  }

  let agentContext: string | null = null
  const intro = signal.agent_introspection
  if (intro) {
    agentContext = `${intro.policy_mode} · thesis ${signal.thesis_signal ?? intro.thesis_signal ?? '—'} · memory ${intro.memory_context_count}`
  }

  let modelConsensusStr: string | null = null
  if (modelConsensus && modelConsensus.confidence > 0) {
    modelConsensusStr = `${formatConfidence(modelConsensus.confidence <= 1 ? modelConsensus.confidence * 100 : modelConsensus.confidence)}${modelConsensus.signal ? ` · ${modelConsensus.signal}` : ''}`
  }

  let reflection: string | null = null
  const ref = signal.reflection_snapshot
  if (ref) {
    const q = ref.quality_score <= 1 ? ref.quality_score * 100 : ref.quality_score
    reflection = `quality ${formatConfidence(q)} · ${ref.calibration_bucket}`
  }

  const hasReasoningChain = Boolean(
    (signal.reasoning_chain && signal.reasoning_chain.length > 0) ||
      signal.reasoning_chain_full?.steps?.length
  )

  const hasContent =
    hypotheses.length > 0 ||
    Boolean(agentContext) ||
    Boolean(modelConsensusStr) ||
    Boolean(reflection) ||
    hasReasoningChain

  return {
    hasContent,
    hypotheses,
    agentContext,
    modelConsensus: modelConsensusStr,
    reflection,
    hasReasoningChain,
  }
}
