import { useEffect, useState } from 'react'
import { useTradingData } from './useTradingData'
import type { Signal } from '@/types'

/**
 * @deprecated Use useTradingData() and its `signal` field directly instead.
 *
 * This wrapper exists for backward compatibility and simply exposes the
 * unified `Signal` from useTradingData as `prediction`.
 */
export function usePredictions(symbol: string = 'BTCUSD') {
  const { signal, isConnected, error } = useTradingData()
  const [prediction, setPrediction] = useState<Signal | null>(null)
  const [loading, setLoading] = useState(true)
  const [localError, setLocalError] = useState<Error | null>(null)

  // Derive prediction from unified trading signal
  useEffect(() => {
    if (!signal) {
      if (isConnected) {
        setLoading(false)
      }
      setPrediction(null)
      return
    }

    if (signal.symbol && signal.symbol !== symbol) {
      setPrediction(null)
      return
    }

    setPrediction(signal)
    setLoading(false)
    setLocalError(null)
  }, [signal, symbol, isConnected])

  // Mirror connection/error semantics from the original hook
  useEffect(() => {
    if (!isConnected && !signal) {
      setLocalError(
        error ?? new Error('WebSocket not connected - unable to receive predictions')
      )
    } else {
      setLocalError(error)
    }
  }, [isConnected, signal, error])

  // Legacy function for backward compatibility (no-op)
  const fetchPrediction = async () => {
    if (process.env.NODE_ENV === 'development') {
      console.log(
        'usePredictions: Deprecated wrapper. Use useTradingData() and select `signal` instead.'
      )
    }
  }

  return { prediction, loading, error: localError, fetchPrediction, isConnected }
}

