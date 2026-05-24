/** Shared helpers for Trading tab display (sides, duration, contract size). */

export function parseFiniteNumber(value: number | string | undefined | null): number | null {
  if (value === undefined || value === null) return null
  const parsed = typeof value === 'number' ? value : parseFloat(String(value))
  return Number.isFinite(parsed) ? parsed : null
}

export function isLongSide(side: string | undefined | null): boolean {
  const s = String(side ?? '').toUpperCase()
  return s === 'BUY' || s === 'LONG'
}

export function isShortSide(side: string | undefined | null): boolean {
  const s = String(side ?? '').toUpperCase()
  return s === 'SELL' || s === 'SHORT'
}

export function sideBadgeVariant(side: string | undefined | null): 'default' | 'destructive' {
  return isLongSide(side) ? 'default' : 'destructive'
}

export function resolveContractValueBtc(
  contractValueBtc?: number | string | null
): number | null {
  const parsed = parseFiniteNumber(contractValueBtc ?? undefined)
  return parsed && parsed > 0 ? parsed : null
}

export function resolveUsdInrRate(usdInrRate?: number | string | null): number | null {
  const parsed = parseFiniteNumber(usdInrRate ?? undefined)
  return parsed && parsed > 0 ? parsed : null
}

export function computeTradeDurationSeconds(
  durationSeconds: number | undefined,
  entryTime: Date | string | undefined,
  exitTime: Date | string | undefined
): number | null {
  if (typeof durationSeconds === 'number' && durationSeconds > 0) {
    return durationSeconds
  }
  if (!entryTime || !exitTime) return null
  const entryMs = new Date(entryTime).getTime()
  const exitMs = new Date(exitTime).getTime()
  if (!Number.isFinite(entryMs) || !Number.isFinite(exitMs)) return null
  const diffSec = Math.floor((exitMs - entryMs) / 1000)
  if (diffSec <= 0) return null
  return diffSec
}

export function formatTradeDuration(durationSeconds: number | null): string {
  if (durationSeconds === null || durationSeconds <= 0) return '—'
  const hours = Math.floor(durationSeconds / 3600)
  const minutes = Math.floor((durationSeconds % 3600) / 60)
  const seconds = durationSeconds % 60
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

export function isTestnetTradingMode(
  tradingMode?: string | null,
  deltaEnvironment?: string | null
): boolean {
  const mode = String(tradingMode ?? '').toLowerCase()
  const env = String(deltaEnvironment ?? '').toLowerCase()
  return mode === 'testnet' || env === 'testnet' || env === 'india_testnet'
}
