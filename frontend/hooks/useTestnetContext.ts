'use client'

import { useMemo } from 'react'
import type { HealthStatus } from '@/types'

export interface TestnetContext {
  isTestnet: boolean
  environmentLabel: string
  tradingReady: boolean | null
  dataSourceLabel: string
  /** False when Delta testnet is unreachable or trading_ready is false */
  testnetConnected: boolean
}

export function useTestnetContext(health?: HealthStatus | null): TestnetContext {
  return useMemo(() => {
    const mode = health?.trading_mode?.toLowerCase()
    const env = health?.delta_environment?.toLowerCase()
    const isTestnet = mode === 'testnet' || env === 'testnet' || env === 'india_testnet'

    const environmentLabel = isTestnet
      ? 'Delta testnet'
      : health?.trading_mode
        ? `${health.trading_mode} trading`
        : 'Trading'

    const deltaSvc = health?.services?.delta_exchange
    const deltaUp =
      deltaSvc && typeof deltaSvc === 'object' && 'status' in deltaSvc
        ? String((deltaSvc as { status?: string }).status).toLowerCase() === 'up'
        : true

    const tradingReady =
      typeof health?.trading_ready === 'boolean' ? health.trading_ready : null
    const testnetConnected =
      !isTestnet || (tradingReady !== false && deltaUp)

    return {
      isTestnet,
      environmentLabel,
      tradingReady,
      dataSourceLabel: isTestnet ? 'Delta testnet account' : 'Trading account',
      testnetConnected,
    }
  }, [health?.trading_mode, health?.delta_environment, health?.trading_ready, health?.services])
}
