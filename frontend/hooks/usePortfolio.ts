import { useState, useEffect } from 'react'
import { apiClient } from '@/services/api'
import { Portfolio } from '@/types'
import { useWebSocket } from './useWebSocket'

// Get WebSocket URL from environment variable
const WS_URL = 
  process.env.NEXT_PUBLIC_WS_URL || 
  (process.env.NODE_ENV === 'development' ? 'ws://localhost:8000/ws' : '')

export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const { isConnected, lastMessage } = useWebSocket(WS_URL)

  // Fetch initial data on mount
  useEffect(() => {
    const fetchPortfolio = async () => {
      try {
        setLoading(true)
        const data = await apiClient.getPortfolioSummary()
        setPortfolio(data)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err : new Error('Failed to fetch portfolio'))
      } finally {
        setLoading(false)
      }
    }

    fetchPortfolio()
  }, [])

  // Handle WebSocket portfolio updates - prioritize these over polling
  useEffect(() => {
    if (lastMessage && lastMessage.type === 'portfolio_update') {
      const portfolioData = lastMessage.data as Portfolio
      if (portfolioData) {
        setPortfolio(portfolioData)
        setError(null)
        setLoading(false)
        
        if (process.env.NODE_ENV === 'development') {
          console.log('[usePortfolio] Portfolio update received via WebSocket:', {
            total_value: portfolioData.total_value,
            open_positions: portfolioData.open_positions,
            positions_count: portfolioData.positions?.length || 0,
            timestamp: portfolioData.timestamp,
            data_source: 'websocket'
          })
        }
      }
    }
  }, [lastMessage])

  // Polling fallback - only when WebSocket is disconnected
  useEffect(() => {
    if (!isConnected) {
      const fetchPortfolio = async () => {
        try {
          const data = await apiClient.getPortfolioSummary()
          setPortfolio(data)
          setError(null)
        } catch (err) {
          setError(err instanceof Error ? err : new Error('Failed to fetch portfolio'))
        }
      }

      // Poll every 5 seconds when WebSocket disconnected
      const interval = setInterval(fetchPortfolio, 5000)
      return () => clearInterval(interval)
    }
    // When WebSocket connects, stop polling - WebSocket updates will handle data
  }, [isConnected])

  return { portfolio, loading, error }
}

