'use client'

import { memo } from 'react'
import type { AgentOverviewPresentation } from '@/utils/agent-overview/agentOverviewPresenter'
import { colorTokenClasses } from './presenterStyles'

export const OpsStrip = memo(function OpsStrip({ ops }: { ops: AgentOverviewPresentation['ops'] }) {
  if (!ops.show || ops.lines.length === 0) return null

  return (
    <div
      className="flex flex-wrap gap-4 rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-xs"
      role="status"
      aria-label="Operational status"
    >
      {ops.lines.map((line) => (
        <div key={line.label} className="flex items-center gap-1.5">
          <span className="text-muted-foreground">{line.label}</span>
          <span className={colorTokenClasses(line.color)}>{line.value}</span>
        </div>
      ))}
    </div>
  )
})
