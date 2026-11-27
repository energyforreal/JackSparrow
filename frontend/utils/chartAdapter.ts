/**
 * Map Market Analysis chart API payloads onto Lightweight Charts view models.
 * Pure helpers — no DOM, safe for unit tests.
 */

import type {
  ChartCandle,
  ChartPatternMarker,
  ChartTimeframe,
  ChartTradePlan,
  ChartVolumeBar,
  MarketChartResponse,
  StructureZone,
} from '@/types'

export type PriceLineKind = 'current' | 'entry' | 'stop_loss' | 'take_profit'

export interface ChartPriceLineView {
  kind: PriceLineKind
  price: number
  title: string
  color: string
  lineStyle: 'solid' | 'dashed'
}

export interface ChartMarkerView {
  time: number
  signal: string
  position: 'belowBar' | 'aboveBar'
  color: string
  shape: 'arrowUp' | 'arrowDown' | 'circle' | 'square'
  text: string
}

export interface ChartZoneView {
  kind: 'support' | 'resistance'
  timeframe: string
  price: number
  low: number
  high: number
  color: string
  label: string
}

export interface ChartViewModel {
  candles: ChartCandle[]
  volume: ChartVolumeBar[]
  priceLines: ChartPriceLineView[]
  markers: ChartMarkerView[]
  zones: ChartZoneView[]
  patterns: ChartPatternMarker[]
  tradePlan: ChartTradePlan
  currentPrice: number | null
}

const TF_SECONDS: Record<string, number> = {
  '5m': 5 * 60,
  '15m': 15 * 60,
  '1h': 60 * 60,
  '4h': 4 * 60 * 60,
}

const BUY_SIGNALS = new Set(['BUY', 'STRONG_BUY'])
const SELL_SIGNALS = new Set(['SELL', 'STRONG_SELL'])

/**
 * Parse candle_timestamp (ISO or Unix) to Unix seconds.
 */
export function toUnixSeconds(value: string | number | null | undefined): number | null {
  if (value == null) return null
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value > 1e12 ? Math.floor(value / 1000) : Math.floor(value)
  }
  const text = String(value).trim()
  if (!text) return null
  const asNumber = Number(text)
  if (Number.isFinite(asNumber) && text === String(asNumber)) {
    return asNumber > 1e12 ? Math.floor(asNumber / 1000) : Math.floor(asNumber)
  }
  const ms = Date.parse(text)
  if (!Number.isFinite(ms)) return null
  return Math.floor(ms / 1000)
}

/**
 * Find the candle open time that contains a decision timestamp.
 */
export function candleTimeForDecision(
  candles: ChartCandle[],
  decisionUnix: number | null,
  timeframe: string
): number | null {
  if (decisionUnix == null || candles.length === 0) return null
  const span = TF_SECONDS[timeframe] ?? TF_SECONDS['15m']
  // Decision timestamps are bar closes, so use (open, open+span].
  for (let i = candles.length - 1; i >= 0; i -= 1) {
    const open = candles[i].time
    if (decisionUnix > open && decisionUnix <= open + span) {
      return open
    }
  }
  let nearest: ChartCandle | null = null
  for (const candle of candles) {
    if (candle.time <= decisionUnix) {
      nearest = candle
    }
  }
  return nearest?.time ?? null
}

/**
 * Snap a pattern bar open onto the visible chart candle open.
 * Pattern times come from 5m/15m source bars; higher TFs need mapping.
 */
export function candleTimeForPattern(
  candles: ChartCandle[],
  patternUnix: number,
  timeframe: string
): number | null {
  if (!Number.isFinite(patternUnix) || candles.length === 0) return null
  const span = TF_SECONDS[timeframe] ?? TF_SECONDS['15m']
  for (let i = candles.length - 1; i >= 0; i -= 1) {
    const open = candles[i].time
    if (patternUnix >= open && patternUnix < open + span) {
      return open
    }
  }
  let nearest: ChartCandle | null = null
  for (const candle of candles) {
    if (candle.time <= patternUnix) {
      nearest = candle
    }
  }
  return nearest?.time ?? null
}

function markerForSignal(
  signal: string,
  time: number
): ChartMarkerView | null {
  const upper = signal.toUpperCase()
  if (BUY_SIGNALS.has(upper)) {
    return {
      time,
      signal: upper,
      position: 'belowBar',
      color: '#16a34a',
      shape: 'arrowUp',
      text: upper.includes('STRONG') ? 'STRONG BUY' : 'BUY',
    }
  }
  if (SELL_SIGNALS.has(upper)) {
    return {
      time,
      signal: upper,
      position: 'aboveBar',
      color: '#dc2626',
      shape: 'arrowDown',
      text: upper.includes('STRONG') ? 'STRONG SELL' : 'SELL',
    }
  }
  return null
}

function markerForPattern(
  pattern: ChartPatternMarker,
  time: number
): ChartMarkerView {
  const bullish = String(pattern.direction).toLowerCase() === 'bullish'
  const isChart = String(pattern.kind).toLowerCase() === 'chart'
  return {
    time,
    signal: pattern.name,
    position: bullish ? 'belowBar' : 'aboveBar',
    color: bullish ? '#0f766e' : '#b91c1c',
    shape: isChart ? 'square' : 'circle',
    text: pattern.label || pattern.name,
  }
}

function zoneViews(
  zones: StructureZone[],
  kind: 'support' | 'resistance'
): ChartZoneView[] {
  const color = kind === 'support' ? 'rgba(22, 163, 74, 0.18)' : 'rgba(220, 38, 38, 0.18)'
  return zones.map((zone) => ({
    kind,
    timeframe: zone.timeframe,
    price: zone.price,
    low: zone.low,
    high: zone.high,
    color,
    label: `${kind === 'support' ? 'Support' : 'Resistance'} ${zone.timeframe.toUpperCase()}`,
  }))
}

/**
 * Build the chart view model from a validated API payload.
 */
export function mapChartPayloadToView(
  payload: MarketChartResponse,
  livePrice?: number | null
): ChartViewModel {
  const plan = payload.trade_plan
  const currentPrice =
    livePrice != null && Number.isFinite(livePrice)
      ? livePrice
      : payload.current_price

  const priceLines: ChartPriceLineView[] = []
  if (currentPrice != null && Number.isFinite(currentPrice)) {
    priceLines.push({
      kind: 'current',
      price: currentPrice,
      title: 'Price',
      color: '#64748b',
      lineStyle: 'dashed',
    })
  }
  if (plan.entry != null && Number.isFinite(plan.entry)) {
    priceLines.push({
      kind: 'entry',
      price: plan.entry,
      title: 'Entry',
      color: '#2563eb',
      lineStyle: 'solid',
    })
  }
  if (plan.stop_loss != null && Number.isFinite(plan.stop_loss)) {
    priceLines.push({
      kind: 'stop_loss',
      price: plan.stop_loss,
      title: 'SL',
      color: '#dc2626',
      lineStyle: 'solid',
    })
  }
  if (plan.take_profit != null && Number.isFinite(plan.take_profit)) {
    priceLines.push({
      kind: 'take_profit',
      price: plan.take_profit,
      title: 'TP',
      color: '#16a34a',
      lineStyle: 'solid',
    })
  }

  const decisionUnix = toUnixSeconds(plan.candle_timestamp)
  const markerTime = candleTimeForDecision(
    payload.candles,
    decisionUnix,
    payload.timeframe
  )
  const markers: ChartMarkerView[] = []
  if (markerTime != null) {
    const marker = markerForSignal(plan.signal, markerTime)
    if (marker) markers.push(marker)
  }

  const patterns = payload.active_patterns || []
  for (const pattern of patterns) {
    const snapped = candleTimeForPattern(
      payload.candles,
      pattern.time,
      payload.timeframe
    )
    if (snapped == null) continue
    markers.push(markerForPattern(pattern, snapped))
  }

  markers.sort((a, b) => a.time - b.time || a.text.localeCompare(b.text))

  return {
    candles: payload.candles,
    volume: payload.volume,
    priceLines,
    markers,
    zones: [
      ...zoneViews(payload.support_zones || [], 'support'),
      ...zoneViews(payload.resistance_zones || [], 'resistance'),
    ],
    patterns,
    tradePlan: plan,
    currentPrice: currentPrice ?? null,
  }
}

export const CHART_TIMEFRAMES: ChartTimeframe[] = ['4h', '1h', '15m', '5m']

export function timeframeLabel(tf: ChartTimeframe): string {
  return tf.toUpperCase()
}
