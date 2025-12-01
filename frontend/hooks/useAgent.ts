import { useState, useEffect } from 'react'
import { useWebSocket } from './useWebSocket'
import { apiClient } from '@/services/api'
import { Portfolio, Trade, Signal } from '@/types'

// Get WebSocket URL from environment variable
// In production, NEXT_PUBLIC_WS_URL must be set
// Fallback to localhost only in development
const WS_URL = 
  process.env.NEXT_PUBLIC_WS_URL || 
  (process.env.NODE_ENV === 'development' ? 'ws://localhost:8000/ws' : '')

export function useAgent() {
  const { isConnected, lastMessage } = useWebSocket(WS_URL)
  const [agentState, setAgentState] = useState<string>('UNKNOWN')
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [recentTrades, setRecentTrades] = useState<Trade[]>([])
  const [signal, setSignal] = useState<Signal | null>(null)
  // Initialize with a stable date to prevent hydration mismatch
  const [lastUpdate, setLastUpdate] = useState<Date>(() => new Date(0))

  useEffect(() => {
    if (lastMessage) {
      switch (lastMessage.type) {
        case 'agent_state': {
          const data = lastMessage.data as { state?: string; last_update?: string | Date; timestamp?: string | Date }
          if (data?.state) {
            setAgentState(data.state)
          }
          // Extract timestamp from message - handle various formats
          if (data?.last_update) {
            setLastUpdate(new Date(data.last_update))
          } else if (data?.timestamp) {
            setLastUpdate(new Date(data.timestamp))
          } else {
            // Use current time if no timestamp provided
            setLastUpdate(new Date())
          }
          break
        }
        case 'portfolio_update':
          setPortfolio(lastMessage.data as Portfolio)
          break
        case 'trade_executed':
          setRecentTrades((prev) => [lastMessage.data as Trade, ...prev].slice(0, 10))
          break
        case 'signal_update':
          const signalData = lastMessage.data as Signal
          setSignal(signalData)
          break
      }
    }
  }, [lastMessage])

  // Fetch initial data on mount, independent of WebSocket state
  useEffect(() => {
    let retryCount = 0
    const maxRetries = 3
    const retryDelay = 1000 // 1 second

    const fetchInitialData = async (): Promise<void> => {
      try {
        // Fetch portfolio data
        const portfolioData = await apiClient.getPortfolioSummary()
        setPortfolio(portfolioData)
        
        // Fetch recent trades
        try {
          const trades = await apiClient.getTrades()
          if (Array.isArray(trades)) {
            setRecentTrades(trades.slice(0, 10)) // Keep only most recent 10
          }
        } catch (tradesError) {
          // Trades fetch is optional, continue with other data
          console.debug('Could not fetch trades:', tradesError)
        }
        
        // Fetch agent status to get initial state and lastUpdate
        try {
          const agentStatus = await apiClient.getAgentStatus()
          if (agentStatus?.state) {
            setAgentState(agentStatus.state)
          }
          // Use current time as fallback
          setLastUpdate(new Date())
        } catch (statusError) {
          // Agent status fetch is optional, continue with portfolio data
          console.debug('Could not fetch agent status:', statusError)
        }
        
        retryCount = 0 // Reset retry count on success
      } catch (error) {
        console.error('Error fetching initial data:', error)
        
        // Retry with exponential backoff
        if (retryCount < maxRetries) {
          retryCount++
          const delay = retryDelay * Math.pow(2, retryCount - 1)
          setTimeout(() => {
            fetchInitialData()
          }, delay)
        }
      }
    }

    // Fetch immediately on mount
    fetchInitialData()
  }, []) // Empty dependency array - only run on mount

  return { agentState, portfolio, recentTrades, signal, isConnected, lastUpdate }
}

