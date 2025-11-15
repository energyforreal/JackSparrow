import { useState, useEffect } from 'react'
import { useWebSocket } from './useWebSocket'
import { apiClient } from '@/services/api'

export function useAgent() {
  const { isConnected, lastMessage } = useWebSocket(
    process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws'
  )
  const [agentState, setAgentState] = useState<string>('UNKNOWN')
  const [portfolio, setPortfolio] = useState<any>(null)
  const [recentTrades, setRecentTrades] = useState<any[]>([])

  useEffect(() => {
    if (lastMessage) {
      switch (lastMessage.type) {
        case 'agent_state':
          setAgentState(lastMessage.data?.state || 'UNKNOWN')
          break
        case 'portfolio_update':
          setPortfolio(lastMessage.data)
          break
        case 'trade_executed':
          setRecentTrades((prev) => [lastMessage.data, ...prev].slice(0, 10))
          break
      }
    }
  }, [lastMessage])

  useEffect(() => {
    // Fetch initial data
    const fetchInitialData = async () => {
      try {
        const portfolioData = await apiClient.getPortfolioSummary()
        setPortfolio(portfolioData)
      } catch (error) {
        console.error('Error fetching initial data:', error)
      }
    }

    if (isConnected) {
      fetchInitialData()
    }
  }, [isConnected])

  return { agentState, portfolio, recentTrades, isConnected }
}

