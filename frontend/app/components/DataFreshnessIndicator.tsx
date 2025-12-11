'use client'

import { cn } from '@/lib/utils'
import { getDataFreshnessColor, formatClockTime, normalizeDate } from '@/utils/formatters'

interface DataFreshnessIndicatorProps {
  timestamp: Date | string | null | undefined
  label?: string
  className?: string
}

function getFreshnessDotColor(timestamp: Date | string | null | undefined): string {
  if (!timestamp) return 'bg-muted-foreground'
  
  const now = new Date()
  // Use normalizeDate to ensure consistent UTC parsing
  const dataTime = normalizeDate(timestamp)
  const ageMs = now.getTime() - dataTime.getTime()
  const ageSeconds = ageMs / 1000
  const ageMinutes = ageSeconds / 60
  
  // Match text color thresholds for consistency
  if (ageSeconds < 30) return 'bg-green-600 dark:bg-green-400'      // Very fresh (< 30s)
  if (ageMinutes < 1) return 'bg-green-500 dark:bg-green-500'      // Fresh (< 1 min)
  if (ageMinutes < 2) return 'bg-yellow-500 dark:bg-yellow-500'    // Recent (< 2 min)
  if (ageMinutes < 5) return 'bg-amber-600 dark:bg-amber-400'      // Moderate (< 5 min)
  if (ageMinutes < 15) return 'bg-orange-600 dark:bg-orange-400'   // Stale (< 15 min)
  return 'bg-red-600 dark:bg-red-400'                               // Very stale (>= 15 min)
}

export function DataFreshnessIndicator({ 
  timestamp, 
  label = 'Last update',
  className 
}: DataFreshnessIndicatorProps) {
  if (!timestamp) {
    if (process.env.NODE_ENV === 'development') {
      console.log('[DataFreshnessIndicator] No timestamp provided:', { label })
    }
    return (
      <span className={cn('text-xs text-muted-foreground', className)}>
        {label}: N/A
      </span>
    )
  }

  // Debug logging in development mode
  if (process.env.NODE_ENV === 'development') {
    const normalized = normalizeDate(timestamp)
    console.log('[DataFreshnessIndicator] Rendering timestamp:', {
      label,
      raw_timestamp: timestamp,
      timestamp_type: typeof timestamp,
      normalized_date: normalized,
      normalized_utc_iso: normalized.toISOString(),
      normalized_local_string: normalized.toString(),
      current_time_utc: new Date().toISOString(),
      current_time_local: new Date().toString(),
      age_ms: new Date().getTime() - normalized.getTime()
    })
  }

  const colorClass = getDataFreshnessColor(timestamp)
  const dotColorClass = getFreshnessDotColor(timestamp)
  const formattedTime = formatClockTime(timestamp)

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
