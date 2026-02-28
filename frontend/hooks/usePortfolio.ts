import { useTradingData } from './useTradingData'

/**
 * @deprecated Use useTradingData() and its `portfolio` field directly instead.
 *
 * This wrapper exists for backward compatibility and simply forwards data
 * from the unified trading data hook.
 */
export function usePortfolio() {
  const { portfolio, isLoading, error } = useTradingData()

  return { portfolio, loading: isLoading, error }
}

