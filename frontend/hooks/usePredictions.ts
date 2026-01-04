import { useState, useEffect } from 'react'
import { useWebSocket } from './useWebSocket'
import { Prediction } from '@/types'

// Get WebSocket URL from environment variable
const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ||
  (process.env.NODE_ENV === 'development' ? 'ws://localhost:8000/ws' : '')

export function usePredictions(symbol: string = 'BTCUSD') {
  const { isConnected, lastMessage } = useWebSocket(WS_URL)
  const [prediction, setPrediction] = useState<Prediction | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  // Listen for WebSocket signal_update messages
  useEffect(() => {
    if (lastMessage?.type === 'signal_update') {
      const signalData = lastMessage.data as Prediction
      if (signalData && signalData.symbol === symbol) {
        setPrediction(signalData)
        setError(null)
        setLoading(false)
      }
    }
  }, [lastMessage, symbol])

  // Set loading to false after connection is established and no data received yet
  useEffect(() => {
    if (isConnected && !prediction) {
      setLoading(false)
    }
  }, [isConnected, prediction])

  // Set error if WebSocket is not connected
  useEffect(() => {
    if (!isConnected && !prediction) {
      setError(new Error('WebSocket not connected - unable to receive predictions'))
    } else if (isConnected) {
      setError(null)
    }
  }, [isConnected, prediction])

  // Legacy function for backward compatibility (no-op since we only use WebSocket)
  const fetchPrediction = async () => {
    // WebSocket-only approach - no manual fetching needed
    console.log('usePredictions: WebSocket-only mode - predictions arrive automatically')
  }

  return { prediction, loading, error, fetchPrediction, isConnected }
}

