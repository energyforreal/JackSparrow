'use client'

import { cn } from '@/lib/utils'
import { getDataFreshnessColor, formatTime } from '@/utils/formatters'

interface DataFreshnessIndicatorProps {
  timestamp: Date | string | null | undefined
  label?: string
  className?: string
}

function getFreshnessDotColor(timestamp: Date | string | null | undefined): string {
  if (!timestamp) return 'bg-muted-foreground'
  
  const now = new Date()
  const dataTime = typeof timestamp === 'string' ? new Date(timestamp) : timestamp
  const ageMs = now.getTime() - dataTime.getTime()
  const ageMinutes = ageMs / (1000 * 60)
  
  if (ageMinutes < 1) return 'bg-green-600 dark:bg-green-400'
  if (ageMinutes < 5) return 'bg-amber-600 dark:bg-amber-400'
  return 'bg-red-600 dark:bg-red-400'
}

export function DataFreshnessIndicator({ 
  timestamp, 
  label = 'Last update',
  className 
}: DataFreshnessIndicatorProps) {
  if (!timestamp) {
    return (
      <span className={cn('text-xs text-muted-foreground', className)}>
        {label}: N/A
      </span>
    )
  }

  const colorClass = getDataFreshnessColor(timestamp)
  const dotColorClass = getFreshnessDotColor(timestamp)
  const formattedTime = formatTime(timestamp)

  return (
    <span className={cn('text-xs flex items-center gap-1.5', className)}>
      <span className="text-muted-foreground">{label}:</span>
      <span className={cn('font-medium', colorClass)}>
        {formattedTime}
      </span>
      <span
        className={cn('h-1.5 w-1.5 rounded-full', dotColorClass)}
        aria-label="Data freshness indicator"
      />
    </span>
  )
}
