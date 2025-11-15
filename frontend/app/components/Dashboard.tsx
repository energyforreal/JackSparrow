'use client'

import { useState, useEffect } from 'react'
import { AgentStatus } from './AgentStatus'
import { PortfolioSummary } from './PortfolioSummary'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useAgent } from '@/hooks/useAgent'

export function Dashboard() {
  const { isConnected, lastMessage } = useWebSocket(
    process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws'
  )
  const { agentState, portfolio, recentTrades } = useAgent()

  return (
    <div className="container mx-auto p-4">
      <h1 className="text-3xl font-bold mb-6">JackSparrow Trading Agent</h1>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <AgentStatus 
          state={agentState} 
          lastUpdate={new Date()}
          isConnected={isConnected}
        />
        
        <PortfolioSummary portfolio={portfolio} />
        
        {/* Additional components will be added here */}
      </div>
    </div>
  )
}

