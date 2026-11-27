'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { getBackendProxyBase } from '@/lib/backendProxy'
import { MarketChartResponseSchema } from '@/schemas/api.validation'
import type { ChartTimeframe, MarketChartResponse, Signal } from '@/types'
import type { MarketData } from '@/hooks/useTradingData'

interface UseChartDataArgs {
  symbol?: string
  timeframe: ChartTimeframe
  signal: Signal | null
  marketTick?: MarketData | null
}

interface UseChartDataResult {
  data: MarketChartResponse | null
  livePrice: number | null
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
}

function decisionKey(signal: Signal | null): string {
  const decision = signal?.trading_decision
  return [
    decision?.decision_id ?? '',
    decision?.candle_timestamp ?? signal?.timestamp ?? '',
    decision?.signal ?? signal?.signal ?? '',
  ].join('|')
}

/**
 * Load chart candles + algorithmic levels; refresh on closed-candle decisions.
 */
export function useChartData({
  symbol = 'BTCUSD',
  timeframe,
  signal,
  marketTick,
}: UseChartDataArgs): UseChartDataResult {
  const [data, setData] = useState<MarketChartResponse | null>(null)
  const [livePrice, setLivePrice] = useState<number | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const lastDecisionKey = useRef<string>('')
  const abortRef = useRef<AbortController | null>(null)

  const fetchChart = useCallback(async () => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setIsLoading(true)
    setError(null)
    try {
      const base = getBackendProxyBase()
      const params = new URLSearchParams({
        symbol,
        timeframe,
        limit: '300',
      })
      const response = await fetch(`${base}/api/v1/market/chart?${params}`, {
        signal: controller.signal,
        headers: { Accept: 'application/json' },
      })
      if (!response.ok) {
        let detail = ''
        try {
          const body = await response.json()
          detail = typeof body?.detail === 'string' ? body.detail : ''
        } catch {
          detail = ''
        }
        throw new Error(
          detail ||
            `Chart request failed (${response.status}). Shared candle data may still be warming up.`
        )
      }
      const json = await response.json()
      const parsed = MarketChartResponseSchema.parse(json)
      setData(parsed as MarketChartResponse)
      if (parsed.current_price != null) {
        setLivePrice(parsed.current_price)
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return
      }
      setError(err instanceof Error ? err.message : 'Failed to load chart')
    } finally {
      setIsLoading(false)
    }
  }, [symbol, timeframe])

  useEffect(() => {
    void fetchChart()
    return () => abortRef.current?.abort()
  }, [fetchChart])

  // Refetch when a new closed-candle decision arrives.
  useEffect(() => {
    const key = decisionKey(signal)
    if (!key || key === '||') return
    if (lastDecisionKey.current === '') {
      lastDecisionKey.current = key
      return
    }
    if (key === lastDecisionKey.current) return
    lastDecisionKey.current = key
    void fetchChart()
  }, [signal, fetchChart])

  // Move only the current-price line on market ticks.
  useEffect(() => {
    const price = marketTick?.price
    if (price != null && Number.isFinite(price) && price > 0) {
      setLivePrice(price)
    }
  }, [marketTick?.price, marketTick?.timestamp])

  return {
    data,
    livePrice,
    isLoading,
    error,
    refetch: fetchChart,
  }
}
