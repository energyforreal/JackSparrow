import { useTradingData } from './useTradingData'

/**
 * @deprecated Use useTradingData() and its selectors instead.
 *
 * This hook is now a thin wrapper around the unified trading data hook to
 * preserve backward compatibility while ensuring a single source of truth.
 */
export function useAgent() {
  const {
    agentState,
    portfolio,
    recentTrades,
    signal,
    isConnected,
    lastUpdate,
    dataSource,
  } = useTradingData()

  return {
    agentState,
    portfolio,
    recentTrades,
    signal,
    isConnected,
    lastUpdate,
    dataSource,
  }
}

