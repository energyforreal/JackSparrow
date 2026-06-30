'use client'

import { memo } from 'react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { AgentOverviewPresentation } from '@/utils/agent-overview/agentOverviewPresenter'

export const ScoreBreakdownSection = memo(function ScoreBreakdownSection({
  scoreBreakdown,
}: {
  scoreBreakdown: AgentOverviewPresentation['scoreBreakdown']
}) {
  if (!scoreBreakdown.visible) return null

  return (
    <section className="space-y-2" aria-label="Trade score breakdown">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold">Trade Score</h3>
        <span className="text-lg font-bold tabular-nums">{scoreBreakdown.totalText}</span>
        {scoreBreakdown.passed != null && (
          <Badge variant={scoreBreakdown.passed ? 'default' : 'secondary'} className="text-[10px]">
            {scoreBreakdown.passed ? 'passed' : 'below min'}
          </Badge>
        )}
      </div>
      <ul className="space-y-2">
        {scoreBreakdown.bars.map((bar) => (
          <li key={bar.label} className="space-y-1">
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">{bar.label}</span>
              <span className="font-medium tabular-nums">{bar.valueText}</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
              <div
                className={cn(
                  'h-full rounded-full transition-all',
                  bar.color === 'success' && 'bg-green-500',
                  bar.color === 'warning' && 'bg-amber-500',
                  bar.color === 'muted' && 'bg-muted-foreground/50'
                )}
                style={{ width: `${bar.percent}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
})
