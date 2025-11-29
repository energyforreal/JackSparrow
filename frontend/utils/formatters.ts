export function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`
}

function normalizeDate(date: Date | string): Date {
  return typeof date === 'string' ? new Date(date) : date
}

function isValidDate(date: Date | string): boolean {
  const d = normalizeDate(date)
  return !Number.isNaN(d.getTime()) && d.getTime() > 0
}

export function formatDate(date: Date | string): string {
  const d = normalizeDate(date)
  return d.toLocaleDateString('en-US', {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function formatTime(date: Date | string): string {
  const d = normalizeDate(date)
  return d.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
  })
}

export function formatDateTime(date: Date | string): string {
  const d = normalizeDate(date)
  const dateStr = d.toLocaleDateString('en-US', {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
  const timeStr = d.toLocaleTimeString('en-US', {
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
  return d.toLocaleDateString('en-US', {
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
  return d.toLocaleTimeString('en-US', {
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
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZoneName: 'short',
    }).formatToParts(d)
    const tzPart = parts.find((part) => part.type === 'timeZoneName')
    return tzPart?.value ?? ''
  } catch {
    return ''
  }
}

