import { useTradingData } from './useTradingData'

/**
 * Canonical portfolio hook for components that need loading/error state.
 *
 * Prefer `useTradingData().portfolio` when you already use the unified hook.
 */
export function usePortfolio() {
  const { portfolio, isLoading, error } = useTradingData()

  return { portfolio, loading: isLoading, error }
}

