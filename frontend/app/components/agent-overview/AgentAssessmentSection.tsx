'use client'

import { memo } from 'react'
import type { AgentOverviewPresentation } from '@/utils/agent-overview/agentOverviewPresenter'

export const AgentAssessmentSection = memo(function AgentAssessmentSection({
  narrative,
}: {
  narrative: AgentOverviewPresentation['narrative']
}) {
  return (
    <section className="min-h-[64px] space-y-1" aria-label="Agent assessment">
      <h3 className="text-sm font-semibold">Agent Assessment</h3>
      <p className="text-sm text-foreground leading-relaxed">{narrative.text}</p>
      {narrative.sourceLabel && (
        <p className="text-[10px] text-muted-foreground">{narrative.sourceLabel}</p>
      )}
    </section>
  )
})
