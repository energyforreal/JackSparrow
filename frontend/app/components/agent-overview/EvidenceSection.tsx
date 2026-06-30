'use client'

import { memo } from 'react'
import type { AgentOverviewPresentation } from '@/utils/agent-overview/agentOverviewPresenter'
import { StatusIcon, colorTokenClasses } from './presenterStyles'

export const EvidenceSection = memo(function EvidenceSection({
  evidence,
}: {
  evidence: AgentOverviewPresentation['evidence']
}) {
  if (!evidence.visible || evidence.rows.length === 0) return null

  return (
    <section className="min-h-[48px] space-y-2" aria-label="Evidence">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Evidence</h3>
        <span className="text-[10px] text-muted-foreground">Why trust this?</span>
      </div>
      <ul className="space-y-1.5">
        {evidence.rows.map((row, i) => (
          <li key={`${row.label}-${i}`} className="flex items-start gap-2 text-sm">
            <StatusIcon kind={row.statusIcon} className="mt-0.5" />
            <div>
              <span className={colorTokenClasses(row.color)}>{row.label}</span>
              {row.detail && (
                <p className="text-xs text-muted-foreground mt-0.5">{row.detail}</p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
})
