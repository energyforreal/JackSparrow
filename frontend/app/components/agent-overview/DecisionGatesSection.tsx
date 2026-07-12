'use client'

import { memo } from 'react'
import type { AgentOverviewPresentation } from '@/utils/agent-overview/agentOverviewPresenter'
import { StatusIcon, colorTokenClasses } from './presenterStyles'

export const DecisionGatesSection = memo(function DecisionGatesSection({
  gates,
}: {
  gates: AgentOverviewPresentation['gates']
}) {
  if (!gates.visible || gates.rows.length === 0) return null

  return (
    <section className="min-h-[48px] space-y-2" aria-label="Decision gates">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Decision Gates</h3>
        <span className="text-[10px] text-muted-foreground">Structural categories</span>
      </div>
      <p className="text-[10px] text-muted-foreground">
        Market-structure checks — not thesis rules (flat thesis can still leave trend/breakout red).
      </p>
      {gates.setupType && gates.setupType !== 'none' && (
        <p className="text-xs text-muted-foreground capitalize">Setup: {gates.setupType.replace(/_/g, ' ')}</p>
      )}
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1.5">
        {gates.rows.map((row) => (
          <li key={row.label} className="flex items-center gap-2 text-sm">
            <StatusIcon kind={row.statusIcon} />
            <span className={colorTokenClasses(row.color)}>{row.label}</span>
          </li>
        ))}
      </ul>
    </section>
  )
})
