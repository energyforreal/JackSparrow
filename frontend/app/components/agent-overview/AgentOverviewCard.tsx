'use client'

import { memo, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { ModelConsensusSnapshot } from '@/hooks/useTradingData'
import type { HealthStatus, Signal } from '@/types'
import {
  composeAgentOverviewView,
  presentAgentOverview,
} from '@/utils/agent-overview'
import { AgentOverviewHero } from './AgentOverviewHero'
import { AgentAssessmentSection } from './AgentAssessmentSection'
import { TradeReadinessSection } from './TradeReadinessSection'
import { DecisionGatesSection } from './DecisionGatesSection'
import { EvidenceSection } from './EvidenceSection'
import { ConfidenceBreakdownSection } from './ConfidenceBreakdownSection'
import { ScoreBreakdownSection } from './ScoreBreakdownSection'
import { RecentEventsSection } from './RecentEventsSection'
import { AgentDiagnosticsAccordion } from './AgentDiagnosticsAccordion'
import { OpsStrip } from './OpsStrip'

export interface AgentOverviewCardProps {
  signal?: Signal | null
  agentState: string
  health?: HealthStatus | null
  modelConsensus?: ModelConsensusSnapshot | null
  isConnected?: boolean
  onOpenAnalysis?: () => void
}

function presentationKey(
  signal: Signal | null | undefined,
  agentState: string,
  health?: HealthStatus | null
): string {
  const ms = signal?.server_timestamp_ms ?? ''
  const ts = signal?.timestamp ?? ''
  const hs = health?.timestamp ?? health?.health_score ?? ''
  return `${agentState}:${ms}:${ts}:${hs}:${signal?.fsm_state}:${signal?.position_lifecycle}`
}

export const AgentOverviewCard = memo(function AgentOverviewCard({
  signal,
  agentState,
  health,
  modelConsensus,
  isConnected = false,
  onOpenAnalysis,
}: AgentOverviewCardProps) {
  const cacheKey = presentationKey(signal, agentState, health)

  const { view, presentation } = useMemo(() => {
    const v = composeAgentOverviewView({
      signal: signal ?? null,
      agentState,
      health,
      modelConsensus,
    })
    return { view: v, presentation: presentAgentOverview(v) }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed by cacheKey
  }, [cacheKey, modelConsensus])

  if (!signal) {
    return (
      <Card role="region" aria-label="Trading agent overview">
        <CardHeader>
          <CardTitle>Trading Agent</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No signal available</p>
          <p className="text-xs text-muted-foreground mt-2">
            Signals appear after a prediction cycle. Press{' '}
            <kbd className="px-1 rounded border border-border text-[10px]">P</kbd> for a manual
            prediction.
          </p>
          {!isConnected && (
            <p className="text-xs text-red-600 dark:text-red-400 mt-2">WebSocket disconnected</p>
          )}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card role="region" aria-label="Trading agent overview" className="h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Trading Agent</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <AgentOverviewHero
          hero={presentation.hero}
          freshnessTimestamp={signal.timestamp}
          serverTimestampMs={signal.server_timestamp_ms}
        />

        <AgentAssessmentSection narrative={presentation.narrative} />

        <TradeReadinessSection readiness={presentation.readiness} />

        <OpsStrip ops={presentation.ops} />

        {view.showManagingSections && signal.thesis_health && (
          <p className="text-sm text-muted-foreground">
            Thesis health:{' '}
            <span className="font-medium text-foreground capitalize">{signal.thesis_health}</span>
          </p>
        )}

        <DecisionGatesSection gates={presentation.gates} />

        <EvidenceSection evidence={presentation.evidence} />

        <ConfidenceBreakdownSection confidence={presentation.confidence} />

        <ScoreBreakdownSection scoreBreakdown={presentation.scoreBreakdown} />

        <RecentEventsSection recentMarketEvents={presentation.recentMarketEvents} />

        <AgentDiagnosticsAccordion view={view} onOpenAnalysis={onOpenAnalysis} />

        <p className="text-[10px] text-muted-foreground text-center">
          Press <kbd className="rounded border bg-muted px-1 font-mono text-[10px]">P</kbd> for
          prediction
        </p>
      </CardContent>
    </Card>
  )
})
