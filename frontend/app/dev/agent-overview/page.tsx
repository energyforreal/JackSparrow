import { notFound } from 'next/navigation'

import { AGENT_OVERVIEW_FIXTURES } from '@/fixtures/agentOverviewSignals'
import { AgentOverviewCard } from '@/app/components/agent-overview/AgentOverviewCard'

export default function AgentOverviewDevPage() {
  if (process.env.NODE_ENV !== 'development') {
    notFound()
  }

  return (
    <div className="container mx-auto px-4 py-8 space-y-8">
      <h1 className="text-2xl font-semibold">Agent Overview — fixture preview</h1>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {AGENT_OVERVIEW_FIXTURES.map((fx) => (
          <div key={fx.id} className="space-y-2">
            <p className="text-sm font-medium text-muted-foreground">{fx.label}</p>
            <AgentOverviewCard
              signal={fx.signal}
              agentState={fx.agentState}
              health={fx.health}
              isConnected
            />
          </div>
        ))}
      </div>
    </div>
  )
}
