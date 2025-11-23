import { useState, useEffect } from 'react'
import { apiClient } from '@/services/api'
import { Portfolio } from '@/types'

export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

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
    const interval = setInterval(fetchPortfolio, 5000) // Refresh every 5 seconds

    return () => clearInterval(interval)
  }, [])

  return { portfolio, loading, error }
}

