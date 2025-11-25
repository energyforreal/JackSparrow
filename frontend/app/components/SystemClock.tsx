'use client'

import { useSystemClock } from '@/hooks/useSystemClock'
import { formatDateTime } from '@/utils/formatters'
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

  return (
    <div
      className={cn(
        'flex items-center gap-2 text-sm font-mono',
        className
      )}
      role="timer"
      aria-live="polite"
      aria-label={`System time: ${formatDateTime(currentTime)}`}
    >
      <Clock
        className={cn(
          'h-4 w-4',
          isSynced ? 'text-muted-foreground' : 'text-yellow-500',
          syncError && 'text-red-500'
        )}
        aria-hidden="true"
      />
      <span className="text-foreground" suppressHydrationWarning>
        {formatDateTime(currentTime)}
      </span>
      {!isSynced && !syncError && (
        <span className="text-xs text-yellow-500" aria-label="Syncing">
          Syncing...
        </span>
      )}
      {syncError && (
        <span className="text-xs text-red-500" aria-label="Sync error">
          Sync Error
        </span>
      )}
    </div>
  )
}

