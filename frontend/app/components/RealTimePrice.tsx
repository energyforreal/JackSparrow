'use client'

import { useState, useEffect, useRef } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { TrendingUp, TrendingDown, Minus, AlertTriangle, TrendingDown as LossIcon, TrendingUp as ProfitIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useWebSocket } from '@/hooks/useWebSocket'
import { usePositionImpact } from '@/hooks/usePositionImpact'
import { Position, EnhancedTickerData } from '@/types'
import { formatCurrency } from '@/utils/formatters'
import { apiClient } from '@/services/api'

interface RealTimePriceProps {
  symbol?: string
  className?: string
  positions?: Position[]
  showPositionImpact?: boolean
}

// Get WebSocket URL from environment variable with Docker/remote-safe defaults
const resolveWebSocketUrl = (): string => {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL
  }

  if (process.env.NODE_ENV === 'development') {
    return 'ws://localhost:8000/ws'
  }

  try {
    if (process.env.NEXT_PUBLIC_API_URL) {
      const api = new URL(process.env.NEXT_PUBLIC_API_URL)
      const wsProtocol = api.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${wsProtocol}//${api.host}/ws`
    }

    if (typeof window !== 'undefined') {
      const { protocol, host } = window.location
      const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:'
      const hostOnly = host.split(':')[0]
      const port = '8000'
      return `${wsProtocol}//${hostOnly}:${port}/ws`
    }
  } catch {
    // Ignore and fall through
  }

  return ''
}

const WS_URL = resolveWebSocketUrl()

const DEFAULT_DOCUMENT_TITLE = 'JackSparrow Trading Agent'

export function RealTimePrice({ symbol = 'BTCUSD', className, positions = [], showPositionImpact = true }: RealTimePriceProps) {
  const { isConnected, lastMessage } = useWebSocket(WS_URL)
  const [ticker, setTicker] = useState<EnhancedTickerData | null>(null)
  const [priceChange, setPriceChange] = useState<number>(0)
  const [isLoading, setIsLoading] = useState(true)
  const [lastPrice, setLastPrice] = useState<number | null>(null)
  const [previousPrice, setPreviousPrice] = useState<number | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<string>('connecting')
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const prevTickPriceRef = useRef<number | null>(null)

  // Component mount diagnostics
  useEffect(() => {
    if (process.env.NODE_ENV === 'development') {
      console.log('[RealTimePrice] Component mounted, WebSocket status:', {
        isConnected,
        hasLastMessage: !!lastMessage,
        url: WS_URL,
        symbol,
      })
      if (!isConnected) {
        console.log(
          '[RealTimePrice] WebSocket not connected, attempting to establish connection...'
        )
      }
    }
    setConnectionStatus(isConnected ? 'connected' : 'connecting')
  }, [isConnected, lastMessage, symbol])

  // Monitor WebSocket connection status
  useEffect(() => {
    setConnectionStatus(isConnected ? 'connected' : 'disconnected')
    if (!isConnected) {
      console.warn('[RealTimePrice] ⚠️ WebSocket disconnected, will attempt reconnection')
    } else {
      console.log('[RealTimePrice] ✅ WebSocket connected')
    }
  }, [isConnected])

  // Debug: Log ticker state changes
  useEffect(() => {
    if (ticker) {
      console.log('[RealTimePrice] 📊 Ticker state updated:', {
        symbol: ticker.symbol,
        price: ticker.price,
        timestamp: ticker.timestamp,
        priceChange,
        connectionStatus
      })
    }
  }, [ticker, priceChange, connectionStatus])

  // Debug: Log incoming WebSocket messages
  useEffect(() => {
    if (lastMessage && process.env.NODE_ENV === 'development') {
      const data = lastMessage.data as Partial<EnhancedTickerData> | undefined
      console.log('[RealTimePrice] 📨 Received WebSocket message:', {
        type: lastMessage.type,
        hasData: !!data,
        symbol: data?.symbol,
        price: data?.price,
        timestamp: new Date().toISOString(),
      })
    }
  }, [lastMessage])

  // Cold-start: fetch the latest ticker over WebSocket commands once connected.
  useEffect(() => {
    let cancelled = false

    const initTicker = async () => {
      if (!isConnected || ticker) return

      setIsLoading(true)
      try {
        const latest = await apiClient.getTicker(symbol)
        if (cancelled) return
        if (latest) {
          setTicker(latest as EnhancedTickerData)
        }
      } catch (error) {
        if (process.env.NODE_ENV === 'development') {
          console.warn('[RealTimePrice] Failed to fetch initial ticker via WS command:', error)
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    initTicker().catch(() => {})
    return () => {
      cancelled = true
    }
  }, [isConnected, ticker, symbol])

  // Initialize price change on first ticker data
  // This ensures momentary price change is calculated as soon as we have initial data
  useEffect(() => {
    if (ticker && lastPrice === null) {
      // Set both lastPrice and previousPrice to initialize change tracking
      // This way, the next price update will show a meaningful change
      if (process.env.NODE_ENV === 'development') {
        console.log('[RealTimePrice] 🎯 Initializing first price point for change tracking')
      }
      setLastPrice(ticker.price)
      setPreviousPrice(ticker.price)
      setPriceChange(0)
    }
  }, [ticker, lastPrice])

  // Handle WebSocket market tick updates - legacy market_tick and unified data_update + resource market
  useEffect(() => {
    const isMarketTick =
      lastMessage?.type === 'market_tick' ||
      (lastMessage?.type === 'data_update' && (lastMessage as { resource?: string }).resource === 'market')
    if (isMarketTick && lastMessage?.data) {
      const tickData = lastMessage.data as EnhancedTickerData
      if (tickData.symbol === symbol) {
        const newPrice = tickData.price
        const oldPrice = lastPrice || ticker?.price

        console.log('[RealTimePrice] Received market update:', {
          symbol: tickData.symbol,
          newPrice,
          oldPrice,
          currentTickerPrice: ticker?.price,
          currentLastPrice: lastPrice
        })

        // Calculate price change BEFORE updating ticker state
        let change = priceChange // Preserve existing change by default
        if (oldPrice && newPrice !== oldPrice) {
          change = newPrice - oldPrice
          console.log('[RealTimePrice] Price change detected:', { oldPrice, newPrice, change })
        } else {
          console.log('[RealTimePrice] No price change detected, preserving existing change:', priceChange)
        }

        // Update all state in a single batch to ensure consistent rendering
        setTicker(tickData)
        setPreviousPrice(oldPrice || null) // Store the price before this update
        setLastPrice(newPrice)
        setPriceChange(change)

        // Keep the momentary price change visible - only update when there's an actual change
        // The change will persist until a new significant change occurs
      }
    }
  }, [lastMessage, symbol, lastPrice, ticker?.price, priceChange])

  // Calculate price change percentage (for real-time change)
  const priceChangePct = ticker && previousPrice && priceChange !== 0 && previousPrice > 0
    ? ((priceChange / previousPrice) * 100)
    : null

  // Determine trend direction
  const trend = priceChange > 0 ? 'up' : priceChange < 0 ? 'down' : 'neutral'
  const trend24h = (ticker?.change_24h_pct || 0) > 0 ? 'up' : (ticker?.change_24h_pct || 0) < 0 ? 'down' : 'neutral'

  // When WebSocket is disconnected, show offline state instead of falling back to REST polling
  useEffect(() => {
    if (!isConnected) {
      setConnectionStatus('disconnected')
    } else {
      setConnectionStatus('connected')
    }
  }, [isConnected])

  // Brief green/red flash on the headline price when the tick changes
  useEffect(() => {
    const price = ticker?.price
    if (price == null || Number.isNaN(Number(price))) return
    const n = Number(price)
    const prev = prevTickPriceRef.current
    if (prev === null) {
      prevTickPriceRef.current = n
      return
    }
    if (n === prev) return
    setFlash(n > prev ? 'up' : 'down')
    prevTickPriceRef.current = n
    const t = window.setTimeout(() => setFlash(null), 600)
    return () => window.clearTimeout(t)
  }, [ticker?.price])

  // Live price in browser tab
  useEffect(() => {
    const price = ticker?.price
    if (price == null || Number.isNaN(Number(price)) || Number(price) <= 0) return
    const n = Number(price)
    const tabPrice = `$${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
    document.title = `${tabPrice} — JackSparrow`
    return () => {
      document.title = DEFAULT_DOCUMENT_TITLE
    }
  }, [ticker?.price])

  const formatPrice = (price: number | null | undefined) => {
    if (!price || price <= 0) return '$0.00'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(price)
  }

  const formatVolume = (volume: number | null | undefined) => {
    if (!volume || volume <= 0) return '0.00'
    if (volume >= 1e9) return `${(volume / 1e9).toFixed(2)}B`
    if (volume >= 1e6) return `${(volume / 1e6).toFixed(2)}M`
    if (volume >= 1e3) return `${(volume / 1e3).toFixed(2)}K`
    return volume.toFixed(2)
  }

  // Position Impact Analysis
  const enhancedTicker: EnhancedTickerData | null = ticker

  const { positionImpacts, summary } = usePositionImpact(positions, enhancedTicker)

  // Position Impact Summary for Tooltip
  const positionImpactTooltip = showPositionImpact && positionImpacts.length > 0 ? {
    totalChange: formatCurrency(summary.totalPnlChange),
    riskLevel: summary.riskiestLevel,
    liquidationRisk: summary.hasLiquidationRisk,
    positionCount: summary.positionCount
  } : null

  return (
    <Card className={cn('relative overflow-hidden', className)} role="region" aria-label={`Real-time price for ${symbol}`}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg font-semibold">{symbol}</CardTitle>
          <div className="flex items-center gap-2">
            <Badge
            variant={connectionStatus === 'connected' ? 'default' : 'secondary'}
            className={cn(
              'text-xs',
              connectionStatus === 'connected' && 'bg-green-500/10 text-green-600 dark:text-green-400',
              connectionStatus === 'polling' && 'bg-yellow-500/10 text-yellow-600 dark:text-yellow-400',
              (connectionStatus === 'disconnected' || connectionStatus === 'error') && 'bg-red-500/10 text-red-600 dark:text-red-400'
            )}
            aria-label={
              connectionStatus === 'connected' ? 'Live WebSocket connection' :
              connectionStatus === 'polling' ? 'Using HTTP polling (WebSocket disconnected)' :
              connectionStatus === 'disconnected' ? 'WebSocket disconnected' :
              'Connection error'
            }
          >
            {connectionStatus === 'connected' ? 'Live' :
             connectionStatus === 'polling' ? 'Polling' :
             connectionStatus === 'connecting' ? 'Connecting...' :
             'Offline'}
          </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && !ticker ? (
          <div className="space-y-2">
            <div className="h-8 w-32 bg-muted animate-pulse rounded" />
            <div className="h-4 w-24 bg-muted animate-pulse rounded" />
            <p className="text-xs text-muted-foreground mt-2">
              Waiting for WebSocket connection...
            </p>
          </div>
        ) : !ticker && (connectionStatus === 'connected' || connectionStatus === 'polling') ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <div className="text-muted-foreground mb-2">
              <svg
                className="mx-auto h-10 w-10 text-muted-foreground/50"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            </div>
            <p className="text-sm font-medium text-foreground mb-1">
              Waiting for Market Data
            </p>
            <p className="text-xs text-muted-foreground">
              Connected to WebSocket, waiting for {symbol} market data...
            </p>
          </div>
        ) : ticker ? (
          <div className="space-y-4">
            {/* Current Price with Momentary Change Indicator */}
            <div className="flex items-center gap-3 flex-wrap">
              <span
                className={cn(
                  'text-4xl font-bold tracking-tight transition-colors duration-300',
                  flash === 'up' && 'text-green-600 dark:text-green-400',
                  flash === 'down' && 'text-red-600 dark:text-red-400',
                  flash === null && 'text-foreground'
                )}
                title={`Current price: ${ticker.price}`}
              >
                {(() => {
                  const formatted = ticker.price ? formatPrice(ticker.price) : '$0.00'
                  if (process.env.NODE_ENV === 'development') {
                    console.log('[RealTimePrice] Rendering price:', { raw: ticker.price, formatted })
                  }
                  return formatted
                })()}
              </span>
              {/* Show momentary/real-time price change - now displayed prominently */}
              {priceChange !== 0 && priceChangePct !== null && (
                <span
                  className={cn(
                    'text-base font-semibold flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg transition-all relative',
                    trend === 'up' && 'text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-950/30 border border-green-200 dark:border-green-900',
                    trend === 'down' && 'text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-950/30 border border-red-200 dark:border-red-900',
                    trend === 'neutral' && 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-950/30 border border-gray-200 dark:border-gray-900'
                  )}
                  title={`Momentary change: ${priceChange > 0 ? '+' : ''}${formatPrice(Math.abs(priceChange))} (${priceChangePct > 0 ? '+' : ''}${priceChangePct.toFixed(2)}%)${positionImpactTooltip ? `\nPosition Impact: ${positionImpactTooltip.totalChange} (${positionImpactTooltip.positionCount} positions)` : ''}`}
                  role="status"
                  aria-live="polite"
                  aria-label={`Price changed by ${priceChange > 0 ? '+' : ''}${priceChangePct.toFixed(2)}%${positionImpactTooltip ? `. Portfolio impact: ${positionImpactTooltip.totalChange}` : ''}`}
                >
                  {trend === 'up' && <TrendingUp className="h-5 w-5 flex-shrink-0" />}
                  {trend === 'down' && <TrendingDown className="h-5 w-5 flex-shrink-0" />}
                  {trend === 'neutral' && <Minus className="h-5 w-5 flex-shrink-0" />}
                  <span className="font-bold">
                    {priceChange > 0 ? '+' : ''}
                    {priceChangePct.toFixed(2)}%
                  </span>
                </span>
              )}

              {/* Position Impact Preview */}
              {showPositionImpact && positionImpacts.length > 0 && (
                <div
                  className={cn(
                    'text-sm font-medium flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border',
                    summary.totalPnlChange > 0 && 'text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-950/30 border-green-200 dark:border-green-900',
                    summary.totalPnlChange < 0 && 'text-red-600 dark:text-red-400 bg-red-100 dark:bg-red-950/30 border-red-200 dark:border-red-900',
                    summary.totalPnlChange === 0 && 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-950/30 border-gray-200 dark:border-gray-900'
                  )}
                  title={`Portfolio Impact: ${formatCurrency(summary.totalPnlChange)} across ${summary.positionCount} positions. Risk Level: ${summary.riskiestLevel}${summary.hasLiquidationRisk ? ' ⚠️ Liquidation Risk' : ''}`}
                  role="status"
                  aria-label={`Portfolio impact: ${formatCurrency(summary.totalPnlChange)}, risk level ${summary.riskiestLevel}`}
                >
                  {summary.totalPnlChange > 0 ? (
                    <ProfitIcon className="h-4 w-4 flex-shrink-0" />
                  ) : summary.totalPnlChange < 0 ? (
                    <LossIcon className="h-4 w-4 flex-shrink-0" />
                  ) : (
                    <Minus className="h-4 w-4 flex-shrink-0" />
                  )}

                  <span className="font-bold">
                    {formatCurrency(summary.totalPnlChange)}
                  </span>

                  {/* Risk Level Indicator */}
                  {summary.riskiestLevel !== 'low' && (
                    <Badge
                      variant="outline"
                      className={cn(
                        'text-xs px-1.5 py-0.5 ml-1',
                        summary.riskiestLevel === 'critical' && 'border-red-500 text-red-600 dark:text-red-400',
                        summary.riskiestLevel === 'high' && 'border-orange-500 text-orange-600 dark:text-orange-400',
                        summary.riskiestLevel === 'medium' && 'border-yellow-500 text-yellow-600 dark:text-yellow-400'
                      )}
                    >
                      {summary.riskiestLevel.toUpperCase()}
                    </Badge>
                  )}

                  {/* Liquidation Risk Warning */}
                  {summary.hasLiquidationRisk && (
                    <AlertTriangle className="h-4 w-4 flex-shrink-0 text-red-500 ml-1" />
                  )}
                </div>
              )}
            </div>

            {/* 24h Stats */}
            <div className="grid grid-cols-2 gap-4 pt-2 border-t">
              <div>
                <div className="text-xs text-muted-foreground mb-1">24h Change</div>
                <div
                  className={cn(
                    'text-sm font-medium',
                    trend24h === 'up' && 'text-green-600 dark:text-green-400',
                    trend24h === 'down' && 'text-red-600 dark:text-red-400',
                    trend24h === 'neutral' && 'text-muted-foreground'
                  )}
                  title={ticker.change_24h_pct === undefined ? '24-hour change data not available from exchange' : undefined}
                >
                  {ticker.change_24h_pct !== undefined && ticker.change_24h_pct !== null
                    ? `${ticker.change_24h_pct > 0 ? '+' : ''}${ticker.change_24h_pct.toFixed(2)}%`
                    : (
                      <span className="text-muted-foreground/70" title="24-hour change data not available">
                        Not available
                      </span>
                    )}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">24h Volume</div>
                <div className="text-sm font-medium">
                  {ticker.volume ? formatVolume(ticker.volume) : '0.00'}
                </div>
              </div>
              {ticker.high_24h && (
                <div>
                  <div className="text-xs text-muted-foreground mb-1">24h High</div>
                  <div className="text-sm font-medium text-green-600 dark:text-green-400">
                    {ticker.high_24h ? formatPrice(ticker.high_24h) : '$0.00'}
                  </div>
                </div>
              )}
              {ticker.low_24h && (
                <div>
                  <div className="text-xs text-muted-foreground mb-1">24h Low</div>
                  <div className="text-sm font-medium text-red-600 dark:text-red-400">
                    {ticker.low_24h ? formatPrice(ticker.low_24h) : '$0.00'}
                  </div>
                </div>
              )}
            </div>

            {/* Price Animation Indicator */}
            {priceChange !== 0 && (
              <div
                className={cn(
                  'absolute top-0 right-0 w-1 h-full transition-opacity duration-300',
                  trend === 'up' && 'bg-green-500/20',
                  trend === 'down' && 'bg-red-500/20'
                )}
              />
            )}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <div className="text-muted-foreground mb-2">
              <svg
                className="mx-auto h-10 w-10 text-muted-foreground/50"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            </div>
            <p className="text-sm font-medium text-foreground mb-1">
              No Price Data Available
            </p>
            <p className="text-xs text-muted-foreground">
              Unable to receive market data for {symbol}.
              {!isConnected && ' WebSocket not connected - check your connection and ensure the backend is running.'}
              {isConnected && ' Connected to WebSocket but no market data received yet.'}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
