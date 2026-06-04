'use client'

import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import { getDataFreshnessColor, formatClockTime, normalizeDate } from '@/utils/formatters'

interface DataFreshnessIndicatorProps {
  timestamp: Date | string | null | undefined
  /** Wall-clock epoch ms from agent emit (server_timestamp_ms); preferred over timestamp when set. */
  serverTimestampMs?: number | null
  label?: string
  className?: string
}

/**
 * Resolve the effective Date for freshness calculations.
 * Prefers serverTimestampMs (set at agent emit, immune to timezone skew)
 * over the ISO timestamp string which may be a bar time after merges.
 */
function resolveEffectiveDate(
  timestamp: Date | string | null | undefined,
  serverTimestampMs: number | null | undefined
): Date | string | null | undefined {
  if (serverTimestampMs != null && Number.isFinite(serverTimestampMs) && serverTimestampMs > 0) {
    return new Date(serverTimestampMs)
  }
  return timestamp
}

function effectiveTimestampKey(
  timestamp: Date | string | null | undefined,
  serverTimestampMs: number | null | undefined
): string {
  if (serverTimestampMs != null && Number.isFinite(serverTimestampMs) && serverTimestampMs > 0) {
    return `ms:${serverTimestampMs}`
  }
  if (timestamp == null || timestamp === '') return 'none'
  return `ts:${String(timestamp)}`
}

function getFreshnessDotColor(timestamp: Date | string | null | undefined): string {
  if (!timestamp) return 'bg-muted-foreground'

  const now = new Date()
  const dataTime = normalizeDate(timestamp)
  const ageMs = now.getTime() - dataTime.getTime()
  const ageSeconds = ageMs / 1000
  const ageMinutes = ageSeconds / 60

  if (ageSeconds < 30) return 'bg-green-600 dark:bg-green-400'
  if (ageMinutes < 1) return 'bg-green-500 dark:bg-green-500'
  if (ageMinutes < 2) return 'bg-yellow-500 dark:bg-yellow-500'
  if (ageMinutes < 5) return 'bg-amber-600 dark:bg-amber-400'
  if (ageMinutes < 15) return 'bg-orange-600 dark:bg-orange-400'
  return 'bg-red-600 dark:bg-red-400'
}

export function DataFreshnessIndicator({
  timestamp,
  serverTimestampMs,
  label = 'Last update',
  className,
}: DataFreshnessIndicatorProps) {
  const effective = resolveEffectiveDate(timestamp, serverTimestampMs)
  const lastLoggedKeyRef = useRef<string | null>(null)

  useEffect(() => {
    if (process.env.NODE_ENV !== 'development') return
    const key = effectiveTimestampKey(timestamp, serverTimestampMs ?? null)
    if (lastLoggedKeyRef.current === key) return
    lastLoggedKeyRef.current = key

    if (!effective) {
      console.log('[DataFreshnessIndicator] No timestamp provided:', { label })
      return
    }
    const normalized = normalizeDate(effective)
    console.log('[DataFreshnessIndicator] Timestamp changed:', {
      label,
      raw_timestamp: timestamp,
      server_timestamp_ms: serverTimestampMs,
      normalized_utc_iso: normalized.toISOString(),
      age_ms: new Date().getTime() - normalized.getTime(),
    })
  }, [effective, timestamp, serverTimestampMs, label])

  if (!effective) {
    return (
      <span className={cn('text-xs text-muted-foreground', className)}>
        {label}: N/A
      </span>
    )
  }

  const colorClass = getDataFreshnessColor(effective)
  const dotColorClass = getFreshnessDotColor(effective)
  const formattedTime = formatClockTime(effective)

  return (
    <span className={cn('text-xs flex items-center gap-1.5', className)}>
      <span className="text-muted-foreground">{label}:</span>
      <span className={cn('font-medium', colorClass)}>{formattedTime}</span>
      <span
        className={cn('h-1.5 w-1.5 rounded-full', dotColorClass)}
        aria-label="Data freshness indicator"
      />
    </span>
  )
}
