const IST_LOCALE = 'en-IN'
const IST_TIMEZONE = 'Asia/Kolkata'

export function formatCurrency(value: number): string {
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue)) {
    return '₹0.00'
  }
  return new Intl.NumberFormat(IST_LOCALE, {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numericValue)
}

export function formatUsdCurrency(value: number): string {
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue)) {
    return '$0.00'
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numericValue)
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
 * 
 * This is the single source of truth for confidence normalization.
 * Use this function everywhere confidence values are processed.
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
 * Alias for normalizeConfidenceToPercent for consistency.
 * Use normalizeConfidence() or normalizeConfidenceToPercent() - both do the same thing.
 */
export const normalizeConfidence = normalizeConfidenceToPercent

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
 * Parse backend ISO timestamps into a Date. If the string has no timezone suffix,
 * treats it as UTC (append `Z`). Returns null for missing, invalid, or pre-2000 values
 * so callers can distinguish bad data from real timestamps.
 */
export function parseUtcTimestamp(
  date: Date | string | null | undefined
): Date | null {
  if (date === null || date === undefined) return null
  if (typeof date === 'string') {
    if (!date.trim()) return null
    const trimmedDate = date.trim()
    const hasExplicitTimezone =
      trimmedDate.endsWith('Z') ||
      /[+-]\d{2}:\d{2}$/.test(trimmedDate) ||
      /[+-]\d{4}$/.test(trimmedDate)
    const isoString = hasExplicitTimezone ? trimmedDate : `${trimmedDate}Z`
    const parsedDate = new Date(isoString)
    if (Number.isNaN(parsedDate.getTime()) || parsedDate.getUTCFullYear() < 2000) {
      return null
    }
    return parsedDate
  }
  if (date instanceof Date) {
    if (Number.isNaN(date.getTime()) || date.getUTCFullYear() < 2000) {
      return null
    }
    return date
  }
  return null
}

/**
 * Calculate data freshness indicator color based on timestamp age.
 * Returns color class for freshness indicators with more granular thresholds.
 */
export function getDataFreshnessColor(timestamp: Date | string | null | undefined): string {
  if (timestamp === null || timestamp === undefined) return 'text-muted-foreground'

  const dataTime = parseUtcTimestamp(timestamp)
  if (!dataTime) return 'text-muted-foreground'

  const now = new Date()
  const ageMs = now.getTime() - dataTime.getTime()
  const ageSeconds = ageMs / 1000
  const ageMinutes = ageSeconds / 60

  if (ageSeconds < 30) return 'text-green-600 dark:text-green-400'
  if (ageMinutes < 1) return 'text-green-500 dark:text-green-500'
  if (ageMinutes < 2) return 'text-yellow-500 dark:text-yellow-500'
  if (ageMinutes < 5) return 'text-amber-600 dark:text-amber-400'
  if (ageMinutes < 15) return 'text-orange-600 dark:text-orange-400'
  return 'text-red-600 dark:text-red-400'
}

/**
 * Normalize a date string or Date object to a Date object.
 * Ensures UTC timestamps are properly parsed before IST conversion.
 *
 * This function is exported so it can be used in hooks to ensure
 * consistent timestamp parsing throughout the application.
 */
export function normalizeDate(date: Date | string | null | undefined): Date {
  if (date === null || date === undefined) {
    if (process.env.NODE_ENV === 'development') {
      console.warn('[normalizeDate] Null or undefined date provided, using current time')
    }
    return new Date()
  }

  if (typeof date === 'string' && !date.trim()) {
    if (process.env.NODE_ENV === 'development') {
      console.warn('[normalizeDate] Empty string date provided, using current time')
    }
    return new Date()
  }

  const parsed = parseUtcTimestamp(date)
  if (parsed) {
    if (process.env.NODE_ENV === 'development' && typeof date === 'string') {
      const trimmedDate = date.trim()
      const hasExplicitTimezone =
        trimmedDate.endsWith('Z') ||
        /[+-]\d{2}:\d{2}$/.test(trimmedDate) ||
        /[+-]\d{4}$/.test(trimmedDate)
      const isoString = hasExplicitTimezone ? trimmedDate : `${trimmedDate}Z`
      console.log('[normalizeDate] Timestamp normalization:', {
        raw_input: date,
        has_explicit_timezone: hasExplicitTimezone,
        normalized_iso_string: isoString,
        parsed_date: parsed,
        parsed_utc_iso: parsed.toISOString(),
        parsed_local_string: parsed.toString(),
        current_time: new Date().toISOString(),
        current_time_local: new Date().toString(),
      })
    }
    if (process.env.NODE_ENV === 'development' && date instanceof Date) {
      console.log('[normalizeDate] Date object passed:', {
        input_date: date,
        utc_iso: date.toISOString(),
        local_string: date.toString(),
      })
    }
    return parsed
  }

  if (typeof date === 'string' || date instanceof Date) {
    if (process.env.NODE_ENV === 'development') {
      const bad =
        typeof date === 'string'
          ? new Date(
              date.trim().endsWith('Z') ||
                /[+-]\d{2}:\d{2}$/.test(date.trim()) ||
                /[+-]\d{4}$/.test(date.trim())
                ? date.trim()
                : `${date.trim()}Z`
            )
          : date
      console.warn('[normalizeDate] Unusable timestamp (invalid or before year 2000):', {
        raw_input: date,
        parsed_probe: bad,
        is_invalid: Number.isNaN(bad.getTime()),
        year_utc: Number.isNaN(bad.getTime()) ? null : bad.getUTCFullYear(),
      })
    }
    return new Date()
  }

  if (process.env.NODE_ENV === 'development') {
    console.warn('[normalizeDate] Unexpected date type:', typeof date, date)
  }
  return new Date()
}

export function isValidDate(date: Date | string | null | undefined): boolean {
  return parseUtcTimestamp(date) !== null
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
  if (date === null || date === undefined) {
    return '--:--:--'
  }
  if (!isValidDate(date)) {
    if (process.env.NODE_ENV === 'development') {
      console.warn('[formatClockTime] Invalid date:', { date })
    }
    return '--:--:--'
  }
  const d = normalizeDate(date)
  const formatted = d.toLocaleTimeString(IST_LOCALE, {
    timeZone: IST_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
  
  // Debug logging in development mode
  if (process.env.NODE_ENV === 'development') {
    console.log('[formatClockTime] Time formatting:', {
      input: date,
      normalized_date: d,
      normalized_utc_iso: d.toISOString(),
      formatted_ist_time: formatted,
      current_time_utc: new Date().toISOString(),
      current_time_ist: new Date().toLocaleTimeString(IST_LOCALE, {
        timeZone: IST_TIMEZONE,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: true,
      })
    })
  }
  
  return formatted
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

