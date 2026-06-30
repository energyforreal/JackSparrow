'use client'

import { memo } from 'react'
import type { AgentOverviewPresentation } from '@/utils/agent-overview/agentOverviewPresenter'

export const RecentEventsSection = memo(function RecentEventsSection({
  recentMarketEvents,
}: {
  recentMarketEvents: AgentOverviewPresentation['recentMarketEvents']
}) {
  if (!recentMarketEvents.visible) return null

  return (
    <section className="space-y-2" aria-label="Recent market events">
      <h3 className="text-sm font-semibold">Market Events</h3>
      <ul className="space-y-1.5 border-l-2 border-muted pl-3">
        {recentMarketEvents.events.map((ev, i) => (
          <li key={`${ev.time}-${i}`} className="text-sm">
            <span className="text-muted-foreground font-mono text-xs mr-2">{ev.time}</span>
            <span className="capitalize">{ev.label}</span>
          </li>
        ))}
      </ul>
    </section>
  )
})
