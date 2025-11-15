'use client'

interface AgentStatusProps {
  state: string
  lastUpdate: Date
  isConnected?: boolean
}

export function AgentStatus({ state, lastUpdate, isConnected = false }: AgentStatusProps) {
  const getStatusColor = () => {
    switch (state) {
      case 'MONITORING':
      case 'OBSERVING':
        return 'bg-green-100 text-green-800'
      case 'THINKING':
      case 'DELIBERATING':
      case 'ANALYZING':
        return 'bg-blue-100 text-blue-800'
      case 'EXECUTING':
        return 'bg-yellow-100 text-yellow-800'
      case 'DEGRADED':
        return 'bg-orange-100 text-orange-800'
      case 'EMERGENCY_STOP':
        return 'bg-red-100 text-red-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h2 className="text-xl font-semibold mb-2">Agent Status</h2>
      <div className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${getStatusColor()}`}>
        {state || 'UNKNOWN'}
      </div>
      <div className="mt-2 text-sm text-gray-600">
        Last Update: {lastUpdate.toLocaleTimeString()}
      </div>
      <div className="mt-2">
        <span className={`inline-block w-2 h-2 rounded-full mr-2 ${isConnected ? 'bg-green-500' : 'bg-red-500'}`}></span>
        {isConnected ? 'Connected' : 'Disconnected'}
      </div>
    </div>
  )
}

