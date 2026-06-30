'use client'

import { memo } from 'react'
import { cn } from '@/lib/utils'
import type { AgentOverviewPresentation } from '@/utils/agent-overview/agentOverviewPresenter'
import { colorTokenClasses } from './presenterStyles'

export const ConfidenceBreakdownSection = memo(function ConfidenceBreakdownSection({
  confidence,
}: {
  confidence: AgentOverviewPresentation['confidence']
}) {
  if (!confidence.visible) return null

  return (
    <section className="space-y-2" aria-label="Confidence breakdown">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold">Confidence</h3>
        <span className="text-lg font-bold tabular-nums">{confidence.aggregateText}</span>
      </div>
      <ul className="space-y-1">
        {confidence.pillars.map((p) => (
          <li key={p.label} className="flex justify-between text-sm">
            <span className="text-muted-foreground">{p.label}</span>
            <span className={cn('font-medium', colorTokenClasses(p.color))}>{p.level}</span>
          </li>
        ))}
      </ul>
    </section>
  )
})
