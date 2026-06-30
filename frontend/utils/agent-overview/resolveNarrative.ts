import { looksLikeProse, synthesizeNarrative } from './catalogs/narrativeCatalog'
import { resolveDecisionReasoning } from '@/utils/signalConfidence'
import { resolveReadinessLabel } from './resolveReadiness'
import type { AgentOverviewInput, NarrativeView } from './types'

export function resolveNarrative(input: AgentOverviewInput): NarrativeView {
  const { signal } = input
  if (!signal) {
    return { text: 'Connect to the agent and request a prediction to see assessment.', source: 'synthesized' }
  }

  const direct = resolveDecisionReasoning(signal)
  if (direct && looksLikeProse(direct)) {
    return { text: direct, source: 'backend' }
  }

  const readiness = resolveReadinessLabel(input)
  return {
    text: synthesizeNarrative(signal, readiness),
    source: 'synthesized',
  }
}
