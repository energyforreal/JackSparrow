import {
  candleTimeForDecision,
  mapChartPayloadToView,
  toUnixSeconds,
} from '@/utils/chartAdapter'
import type { MarketChartResponse } from '@/types'

const samplePayload = (): MarketChartResponse => ({
  symbol: 'BTCUSD',
  timeframe: '15m',
  candles: [
    { time: 1_700_000_000, open: 100, high: 101, low: 99, close: 100.5 },
    { time: 1_700_000_900, open: 100.5, high: 102, low: 100, close: 101.5 },
    { time: 1_700_001_800, open: 101.5, high: 103, low: 101, close: 102 },
  ],
  volume: [
    { time: 1_700_000_000, value: 10 },
    { time: 1_700_000_900, value: 12 },
    { time: 1_700_001_800, value: 8 },
  ],
  current_price: 102.2,
  support_zones: [
    { timeframe: '1h', price: 98, low: 97.5, high: 98.5 },
    { timeframe: '4h', price: 95, low: 94, high: 96 },
  ],
  resistance_zones: [
    { timeframe: '1h', price: 110, low: 109, high: 111 },
  ],
  active_patterns: [
    {
      time: 1_700_000_900,
      name: 'cdl_hammer',
      label: 'Hammer',
      direction: 'bullish',
      timeframe: '5m',
      kind: 'candlestick',
      price: 100.8,
    },
    {
      time: 1_700_001_800,
      name: 'chp_bear_flag',
      label: 'Bear Flag',
      direction: 'bearish',
      timeframe: '15m',
      kind: 'chart',
      price: 102.0,
    },
  ],
  trade_plan: {
    signal: 'BUY',
    entry: 101.5,
    stop_loss: 98,
    take_profit: 108,
    score: 78,
    risk_reward: 1.857,
    valid: true,
    candle_timestamp: '2023-11-14T22:20:00.000Z',
    decision_id: 'd1',
  },
})

describe('chartAdapter', () => {
  it('maps payload onto candles, price lines, markers, and zones', () => {
    const payload = samplePayload()
    // Decision time inside the second 15m candle (open 1700000900)
    payload.trade_plan.candle_timestamp = new Date(
      1_700_000_900 * 1000 + 60_000
    ).toISOString()

    const view = mapChartPayloadToView(payload)

    expect(view.candles).toHaveLength(3)
    expect(view.volume).toHaveLength(3)

    const kinds = view.priceLines.map((line) => line.kind)
    expect(kinds).toEqual(
      expect.arrayContaining(['current', 'entry', 'stop_loss', 'take_profit'])
    )
    expect(view.priceLines.find((l) => l.kind === 'entry')?.price).toBe(101.5)
    expect(view.priceLines.find((l) => l.kind === 'current')?.lineStyle).toBe(
      'dashed'
    )

    expect(view.markers.length).toBeGreaterThanOrEqual(3)
    const signal = view.markers.find((m) => m.shape === 'arrowUp')
    expect(signal?.time).toBe(1_700_000_900)
    const hammer = view.markers.find((m) => m.text === 'Hammer')
    expect(hammer?.shape).toBe('circle')
    expect(hammer?.position).toBe('belowBar')
    const bearFlag = view.markers.find((m) => m.text === 'Bear Flag')
    expect(bearFlag?.shape).toBe('square')
    expect(bearFlag?.position).toBe('aboveBar')
    expect(view.patterns).toHaveLength(2)

    expect(view.zones).toHaveLength(3)
    expect(view.zones.filter((z) => z.kind === 'support')).toHaveLength(2)
    expect(view.zones.filter((z) => z.kind === 'resistance')).toHaveLength(1)
  })

  it('prefers live price for the current-price line', () => {
    const view = mapChartPayloadToView(samplePayload(), 103.5)
    expect(view.currentPrice).toBe(103.5)
    expect(view.priceLines.find((l) => l.kind === 'current')?.price).toBe(103.5)
  })

  it('omits directional overlays on HOLD but keeps pattern markers', () => {
    const payload = samplePayload()
    payload.trade_plan = {
      ...payload.trade_plan,
      signal: 'HOLD',
      entry: null,
      stop_loss: null,
      take_profit: null,
      valid: false,
    }
    const view = mapChartPayloadToView(payload)
    expect(view.markers.every((m) => m.shape !== 'arrowUp' && m.shape !== 'arrowDown')).toBe(
      true
    )
    expect(view.markers.some((m) => m.text === 'Hammer')).toBe(true)
    expect(view.priceLines.map((l) => l.kind)).toEqual(['current'])
  })

  it('parses unix and ISO timestamps', () => {
    expect(toUnixSeconds(1_700_000_000)).toBe(1_700_000_000)
    expect(toUnixSeconds(1_700_000_000_000)).toBe(1_700_000_000)
    expect(toUnixSeconds('2023-11-14T22:13:20.000Z')).toBe(1_700_000_000)
  })

  it('finds the candle that contains a decision close', () => {
    const candles = samplePayload().candles
    // Mid-bar decision
    expect(candleTimeForDecision(candles, 1_700_000_900 + 60, '15m')).toBe(
      1_700_000_900
    )
    // Exact bar close maps to that bar's open, not the next open
    expect(candleTimeForDecision(candles, 1_700_000_900 + 900, '15m')).toBe(
      1_700_000_900
    )
  })
})
