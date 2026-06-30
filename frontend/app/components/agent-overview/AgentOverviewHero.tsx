'use client'

import { memo } from 'react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { PresentedHero } from '@/utils/agent-overview/agentOverviewPresenter'
import { colorTokenBg, colorTokenClasses } from './presenterStyles'
import { DataFreshnessIndicator } from '../DataFreshnessIndicator'

interface AgentOverviewHeroProps {
  hero: PresentedHero
  freshnessTimestamp?: string | Date | null
  serverTimestampMs?: number | null
}

function getSignalBadgeClasses(direction: string): string {
  if (direction.includes('STRONG LONG') || direction === 'LONG') {
    return 'bg-success text-white'
  }
  if (direction.includes('STRONG SHORT') || direction === 'SHORT') {
    return 'bg-error text-white'
  }
  return 'bg-muted text-muted-foreground'
}

export const AgentOverviewHero = memo(function AgentOverviewHero({
  hero,
  freshnessTimestamp,
  serverTimestampMs,
}: AgentOverviewHeroProps) {
  return (
    <div
      className={cn(
        'rounded-lg border p-4 space-y-3',
        colorTokenBg(hero.directionColor),
        hero.minHeight
      )}
      role="status"
      aria-label={`Agent decision: ${hero.directionLabel}, ${hero.lifecycleLabel}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <Badge className={cn('text-lg px-4 py-2 font-bold', getSignalBadgeClasses(hero.directionLabel))}>
            {hero.directionLabel}
          </Badge>
          <p className={cn('text-base font-semibold', colorTokenClasses(hero.lifecycleColor))}>
            {hero.lifecycleLabel}
          </p>
          {hero.fsmLabel && hero.fsmLabel !== hero.lifecycleLabel && (
            <p className="text-xs text-muted-foreground">{hero.fsmLabel}</p>
          )}
          {hero.regimeText && (
            <p className="text-xs text-muted-foreground capitalize">{hero.regimeText}</p>
          )}
        </div>
        <div className="text-right space-y-1 tabular-nums">
          {hero.tradeScoreText != null && (
            <div>
              <p className="text-xs text-muted-foreground">Trade score</p>
              <p className="text-2xl font-bold">
                {hero.tradeScoreText}
                <span className="text-sm font-normal text-muted-foreground"> /100</span>
              </p>
            </div>
          )}
          <div>
            <p className="text-xs text-muted-foreground">Confidence</p>
            <p className="text-xl font-semibold">{hero.confidenceText}</p>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border/50 text-xs">
        {hero.runtimeLabel && (
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-amber-500" aria-hidden />
            <span className="text-muted-foreground">{hero.runtimeLabel}</span>
          </span>
        )}
        <DataFreshnessIndicator
          timestamp={freshnessTimestamp}
          serverTimestampMs={serverTimestampMs}
          className="ml-auto"
        />
      </div>
    </div>
  )
})
