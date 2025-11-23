import { useState, useEffect } from 'react'
import { apiClient } from '@/services/api'
import { Prediction } from '@/types'

export function usePredictions(symbol: string = 'BTCUSD') {
  const [prediction, setPrediction] = useState<Prediction | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const fetchPrediction = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getPrediction(symbol)
      setPrediction(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch prediction'))
    } finally {
      setLoading(false)
    }
  }

  return { prediction, loading, error, fetchPrediction }
}

