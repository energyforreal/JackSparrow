const IST_LOCALE = 'en-IN'
const IST_TIMEZONE = 'Asia/Kolkata'

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat(IST_LOCALE, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`
}

/**
 * Normalize a confidence value to a 0-100 percentage.
 *
 * Backends sometimes return confidences in the 0-1 range while
 * WebSocket payloads may already be in 0-100. This helper accepts
 * either and always returns a clamped percentage for display.
 */
export function normalizeConfidenceToPercent(
  value: number | null | undefined
): number {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 0
  }

  // If the value already looks like a percentage, clamp to [0, 100].
  if (value > 1) {
    if (value < 0) return 0
    if (value > 100) return 100
    return value
  }

  // Treat as 0-1 float and convert to percentage.
  if (value < 0) {
    return 0
  }

  return Math.min(100, Math.max(0, value * 100))
}

/**
 * Format confidence as a percentage string with consistent decimal places.
 * Always returns format like "49.7%" or "0.0%"
 */
export function formatConfidence(value: number | null | undefined): string {
  const percent = normalizeConfidenceToPercent(value)
  return `${percent.toFixed(1)}%`
}

/**
 * Get color class for confidence level based on thresholds.
 * Returns Tailwind classes for progress bar colors.
 */
export function getConfidenceColorClass(confidence: number): string {
  const percent = normalizeConfidenceToPercent(confidence)
  if (percent < 50) {
    return 'bg-red-500'
  } else if (percent < 75) {
    return 'bg-amber-500'
  } else {
    return 'bg-green-500'
  }
}

/**
 * Calculate data freshness indicator color based on timestamp age.
 * Returns color class for freshness indicators.
 */
export function getDataFreshnessColor(timestamp: Date | string | null | undefined): string {
  if (!timestamp) return 'text-muted-foreground'
  
  const now = new Date()
  const dataTime = typeof timestamp === 'string' ? new Date(timestamp) : timestamp
  const ageMs = now.getTime() - dataTime.getTime()
  const ageMinutes = ageMs / (1000 * 60)
  
  if (ageMinutes < 1) return 'text-green-600 dark:text-green-400'
  if (ageMinutes < 5) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
}

function normalizeDate(date: Date | string): Date {
  if (typeof date === 'string') {
    // Backend currently sends timestamps like "2025-12-02T10:11:11.976865"
    // without an explicit timezone. Those should be treated as UTC and then
    // displayed in IST on the frontend.
    //
    // Heuristic:
    // - If the string already has a timezone (ends with Z or contains +hh:mm/-hh:mm),
    //   let the Date constructor handle it.
    // - Otherwise, assume UTC by appending 'Z'.
    const hasExplicitTimezone =
      date.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(date)

    const isoString = hasExplicitTimezone ? date : `${date}Z`
    return new Date(isoString)
  }
  return date
}

function isValidDate(date: Date | string): boolean {
  const d = normalizeDate(date)
  return !Number.isNaN(d.getTime()) && d.getTime() > 0
}

export function formatDate(date: Date | string): string {
  const d = normalizeDate(date)
  return d.toLocaleDateString(IST_LOCALE, {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function formatTime(date: Date | string): string {
  const d = normalizeDate(date)
  return d.toLocaleTimeString(IST_LOCALE, {
    timeZone: IST_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}

export function formatDateTime(date: Date | string): string {
  const d = normalizeDate(date)
  const dateStr = d.toLocaleDateString(IST_LOCALE, {
    timeZone: IST_TIMEZONE,
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
  const timeStr = d.toLocaleTimeString(IST_LOCALE, {
    timeZone: IST_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
  return `${dateStr} | ${timeStr}`
}

export function formatPrice(value: number, decimals: number = 2): string {
  return value.toFixed(decimals)
}

export function formatClockDate(date: Date | string | null | undefined): string {
  if (!date || !isValidDate(date)) {
    return 'Syncing…'
  }
  const d = normalizeDate(date)
  return d.toLocaleDateString(IST_LOCALE, {
    timeZone: IST_TIMEZONE,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

export function formatClockTime(date: Date | string | null | undefined): string {
  if (!date || !isValidDate(date)) {
    return '--:--:--'
  }
  const d = normalizeDate(date)
  return d.toLocaleTimeString(IST_LOCALE, {
    timeZone: IST_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}

export function formatTimezone(date: Date | string | null | undefined): string {
  if (!date || !isValidDate(date)) {
    return ''
  }
  try {
    const d = normalizeDate(date)
    const parts = new Intl.DateTimeFormat(IST_LOCALE, {
      timeZone: IST_TIMEZONE,
      timeZoneName: 'short',
    }).formatToParts(d)
    const tzPart = parts.find((part) => part.type === 'timeZoneName')
    return tzPart?.value ?? ''
  } catch {
    return ''
  }
}

