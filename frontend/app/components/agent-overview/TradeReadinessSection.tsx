'use client'

import { memo } from 'react'
import type { PresentedReadiness } from '@/utils/agent-overview/agentOverviewPresenter'
import { colorTokenClasses } from './presenterStyles'
import { cn } from '@/lib/utils'

export const TradeReadinessSection = memo(function TradeReadinessSection({
  readiness,
}: {
  readiness: PresentedReadiness
}) {
  return (
    <section className={cn('space-y-2', readiness.minHeight)} aria-label="Trade readiness">
      <h3 className="text-sm font-semibold">Trade Readiness</h3>
      <p className={cn('text-sm font-medium', colorTokenClasses(readiness.labelColor))}>
        {readiness.label}
      </p>
      {readiness.blockedReason && (
        <p className="text-xs text-red-600 dark:text-red-400">{readiness.blockedReason}</p>
      )}
      {readiness.subMetrics.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {readiness.subMetrics.map((m) => (
            <div key={m.label} className="text-xs">
              <span className="text-muted-foreground">{m.label}: </span>
              <span className="font-medium tabular-nums">{m.value}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
})
