'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useWebSocket } from '@/hooks/useWebSocket'
import { apiClient } from '@/services/api'

interface TickerData {
  symbol: string
  price: number
  volume: number
  timestamp: string | Date
  change_24h?: number
  change_24h_pct?: number
  high_24h?: number
  low_24h?: number
}

interface RealTimePriceProps {
  symbol?: string
  className?: string
}

// Get WebSocket URL from environment variable
const WS_URL = 
  process.env.NEXT_PUBLIC_WS_URL || 
  (process.env.NODE_ENV === 'development' ? 'ws://localhost:8000/ws' : '')

export function RealTimePrice({ symbol = 'BTCUSD', className }: RealTimePriceProps) {
  const { isConnected, lastMessage } = useWebSocket(WS_URL)
  const [ticker, setTicker] = useState<TickerData | null>(null)
  const [priceChange, setPriceChange] = useState<number>(0)
  const [isLoading, setIsLoading] = useState(true)
  const [lastPrice, setLastPrice] = useState<number | null>(null)

  // Fetch initial ticker data
  useEffect(() => {
    const fetchTicker = async () => {
      try {
        setIsLoading(true)
        const data = await apiClient.request<TickerData>(`/api/v1/market/ticker?symbol=${symbol}`)
        if (data) {
          setTicker(data)
          setLastPrice(data.price)
          setPriceChange(0)
        }
      } catch (error) {
        console.error('Failed to fetch ticker:', error)
      } finally {
        setIsLoading(false)
      }
    }

    fetchTicker()
    // Refresh ticker every 30 seconds as fallback
    const interval = setInterval(fetchTicker, 30000)
    return () => clearInterval(interval)
  }, [symbol])

  // Handle WebSocket market tick updates
  useEffect(() => {
    if (lastMessage?.type === 'market_tick') {
      const tickData = lastMessage.data as TickerData
      if (tickData.symbol === symbol) {
        const newPrice = tickData.price
        const oldPrice = lastPrice || ticker?.price
        
        if (oldPrice && newPrice !== oldPrice) {
          setPriceChange(newPrice - oldPrice)
          // Reset price change indicator after 3 seconds
          const timeout = setTimeout(() => {
            setPriceChange(0)
          }, 3000)
          return () => clearTimeout(timeout)
        }
        
        setTicker(tickData)
        setLastPrice(newPrice)
      }
    }
  }, [lastMessage, symbol, lastPrice, ticker?.price])

  // Calculate price change percentage (for real-time change)
  const priceChangePct = ticker && lastPrice && priceChange !== 0 && (lastPrice - priceChange) > 0
    ? ((priceChange / (lastPrice - priceChange)) * 100)
    : null

  // Determine trend direction
  const trend = priceChange > 0 ? 'up' : priceChange < 0 ? 'down' : 'neutral'
  const trend24h = (ticker?.change_24h_pct || 0) > 0 ? 'up' : (ticker?.change_24h_pct || 0) < 0 ? 'down' : 'neutral'

  const formatPrice = (price: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(price)
  }

  const formatVolume = (volume: number) => {
    if (volume >= 1e9) return `${(volume / 1e9).toFixed(2)}B`
    if (volume >= 1e6) return `${(volume / 1e6).toFixed(2)}M`
    if (volume >= 1e3) return `${(volume / 1e3).toFixed(2)}K`
    return volume.toFixed(2)
  }

  return (
    <Card className={cn('relative overflow-hidden', className)}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg font-semibold">{symbol}</CardTitle>
          <Badge
            variant={isConnected ? 'default' : 'secondary'}
            className={cn(
              'text-xs',
              isConnected && 'bg-green-500/10 text-green-600 dark:text-green-400',
              !isConnected && 'bg-gray-500/10 text-gray-600 dark:text-gray-400'
            )}
          >
            {isConnected ? 'Live' : 'Offline'}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading && !ticker ? (
          <div className="space-y-2">
            <div className="h-8 w-32 bg-muted animate-pulse rounded" />
            <div className="h-4 w-24 bg-muted animate-pulse rounded" />
          </div>
        ) : ticker ? (
          <div className="space-y-4">
            {/* Current Price */}
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-bold tracking-tight">
                {formatPrice(ticker.price)}
              </span>
              {priceChange !== 0 && (
                <span
                  className={cn(
                    'text-sm font-medium flex items-center gap-1',
                    trend === 'up' && 'text-green-600 dark:text-green-400',
                    trend === 'down' && 'text-red-600 dark:text-red-400',
                    trend === 'neutral' && 'text-muted-foreground'
                  )}
                >
                  {trend === 'up' && <TrendingUp className="h-4 w-4" />}
                  {trend === 'down' && <TrendingDown className="h-4 w-4" />}
                  {trend === 'neutral' && <Minus className="h-4 w-4" />}
                  {priceChange > 0 ? '+' : ''}
                  {formatPrice(Math.abs(priceChange))}
                  {priceChangePct !== null && priceChangePct !== 0 && (
                    <span className="text-xs">
                      ({priceChangePct > 0 ? '+' : ''}
                      {priceChangePct.toFixed(2)}%)
                    </span>
                  )}
                </span>
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
                >
                  {ticker.change_24h_pct !== undefined
                    ? `${ticker.change_24h_pct > 0 ? '+' : ''}${ticker.change_24h_pct.toFixed(2)}%`
                    : 'N/A'}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground mb-1">24h Volume</div>
                <div className="text-sm font-medium">
                  {formatVolume(ticker.volume)}
                </div>
              </div>
              {ticker.high_24h && (
                <div>
                  <div className="text-xs text-muted-foreground mb-1">24h High</div>
                  <div className="text-sm font-medium text-green-600 dark:text-green-400">
                    {formatPrice(ticker.high_24h)}
                  </div>
                </div>
              )}
              {ticker.low_24h && (
                <div>
                  <div className="text-xs text-muted-foreground mb-1">24h Low</div>
                  <div className="text-sm font-medium text-red-600 dark:text-red-400">
                    {formatPrice(ticker.low_24h)}
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
          <div className="text-sm text-muted-foreground">No price data available</div>
        )}
      </CardContent>
    </Card>
  )
}
