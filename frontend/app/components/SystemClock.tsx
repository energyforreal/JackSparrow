'use client'

import { useSystemClock } from '@/hooks/useSystemClock'
import { formatClockDate, formatClockTime, formatTimezone } from '@/utils/formatters'
import { Clock } from 'lucide-react'
import { cn } from '@/lib/utils'

interface SystemClockProps {
  className?: string
}

/**
 * SystemClock component displays real-time synchronized system clock.
 * 
 * Features:
 * - Shows date and time in format: "Mon, Jan 12, 2025 | 10:30:45 AM"
 * - Auto-updates every second
 * - Synchronized with backend server time
 * - Visual indicator for sync status
 */
export function SystemClock({ className }: SystemClockProps) {
  const { currentTime, isSynced, syncError } = useSystemClock()
  const timeLabel = formatClockTime(currentTime)
  const dateLabel = formatClockDate(currentTime)
  const timezone = formatTimezone(currentTime)

  const status = syncError ? 'error' : isSynced ? 'synced' : 'syncing'
  const statusLabel =
    status === 'error' ? 'Sync Error' : status === 'synced' ? 'Synced' : 'Syncing…'
  const statusClasses = cn(
    'rounded-full px-2 py-0.5 text-xs font-medium',
    status === 'synced' && 'bg-success/10 text-success',
    status === 'syncing' && 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-200',
    status === 'error' && 'bg-error/10 text-error'
  )

  return (
    <div
      className={cn(
        'flex flex-col gap-2 text-sm font-mono',
        className
      )}
      role="timer"
      aria-live="polite"
      aria-label={`System time ${timeLabel}. ${dateLabel}`}
    >
      <div className="flex items-center gap-3">
        <div
          className={cn(
            'flex h-8 w-8 items-center justify-center rounded-full border',
            status === 'synced' && 'border-muted text-muted-foreground',
            status === 'syncing' && 'border-amber-300 text-amber-500 dark:border-amber-500/40',
            status === 'error' && 'border-error/50 text-error'
          )}
          aria-hidden="true"
        >
          <Clock className="h-4 w-4" />
        </div>
        <div className="flex flex-col leading-tight">
          <span className="text-base font-semibold tracking-wide text-foreground" suppressHydrationWarning>
            {timeLabel}
          </span>
          <span className="text-xs text-muted-foreground" suppressHydrationWarning>
            {dateLabel}
          </span>
        </div>
        {timezone && (
          <span className="rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground" suppressHydrationWarning>
            {timezone}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 text-xs">
        <span className={statusClasses} aria-live="polite">
          {statusLabel}
        </span>
        {!syncError && (
          <span className="text-muted-foreground">
            Updated every second · server synced
          </span>
        )}
        {syncError && (
          <span className="text-error">
            Unable to reach time service
          </span>
        )}
      </div>
    </div>
  )
}

