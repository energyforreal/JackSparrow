import { resolveConfidence } from './resolveConfidence'
import { resolveDiagnostics } from './resolveDiagnostics'
import { resolveEvidence } from './resolveEvidence'
import { resolveGates } from './resolveGates'
import { resolveHero, resolveMode } from './resolveHero'
import { resolveNarrative } from './resolveNarrative'
import { resolveOpsContext } from './resolveOpsContext'
import { resolveReadiness } from './resolveReadiness'
import { resolveRecentEvents } from './resolveRecentEvents'
import { resolveScoreBreakdown } from './resolveScoreBreakdown'
import type { AgentOverviewInput, AgentOverviewView } from './types'

export function composeAgentOverviewView(input: AgentOverviewInput): AgentOverviewView {
  const mode = resolveMode(input.signal)
  const showManagingSections = mode === 'managing'
  const showEntrySections = mode === 'entry' || mode === 'flat'

  return {
    mode,
    hero: resolveHero(input),
    readiness: resolveReadiness(input),
    gates: resolveGates(input),
    evidence: resolveEvidence(input),
    narrative: resolveNarrative(input),
    confidence: resolveConfidence(input),
    scoreBreakdown: resolveScoreBreakdown(input),
    recentMarketEvents: resolveRecentEvents(input),
    diagnostics: resolveDiagnostics(input),
    ops: resolveOpsContext(input),
    showEntrySections,
    showManagingSections,
  }
}
