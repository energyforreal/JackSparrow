// Define contract size (1 lot = 0.001 BTC on Delta Exchange)
const CONTRACT_VALUE_BTC = 0.001

export function calculatePnL(
  entryPrice: number,
  currentPrice: number,
  quantity: number,
  side: string,
  contractValueBtc: number = CONTRACT_VALUE_BTC
): number {
  const btcQuantity = quantity * contractValueBtc
  if (side === 'BUY' || side === 'LONG') {
    return (currentPrice - entryPrice) * btcQuantity
  } else {
    return (entryPrice - currentPrice) * btcQuantity
  }
}

export function calculatePnLPercent(entryPrice: number, currentPrice: number, side: string): number {
  if (!entryPrice || entryPrice === 0) {
    return 0
  }
  if (side === 'BUY') {
    return ((currentPrice - entryPrice) / entryPrice) * 100
  } else {
    return ((entryPrice - currentPrice) / entryPrice) * 100
  }
}

export function calculateReturn(initial: number, current: number): number {
  if (!initial || initial === 0) {
    return 0
  }
  return ((current - initial) / initial) * 100
}

// Position Impact Analysis Functions
export function calculatePositionImpact(
  entryPrice: number,
  currentPrice: number,
  quantity: number,
  side: string,
  stopLoss?: number,
  contractValueBtc: number = CONTRACT_VALUE_BTC
): {
  pnlChange: number
  pnlPercent: number
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  liquidationRisk: boolean
  currentValue: number
  entryValue: number
} {
  // Calculate P&L change using contract size
  const pnlChange = calculatePnL(entryPrice, currentPrice, quantity, side, contractValueBtc)

  // Calculate position values with contract size
  const btcQuantity = quantity * contractValueBtc
  const entryValue = entryPrice * btcQuantity
  const currentValue = entryValue + pnlChange

  // Calculate percentage change
  const pnlPercent = Math.abs(pnlChange) / entryValue

  // Determine risk level based on P&L percentage
  let riskLevel: 'low' | 'medium' | 'high' | 'critical' = 'low'
  if (pnlPercent > 0.10) riskLevel = 'critical'        // >10% change
  else if (pnlPercent > 0.05) riskLevel = 'high'       // >5% change
  else if (pnlPercent > 0.02) riskLevel = 'medium'     // >2% change

  // Check liquidation risk (simplified - would need exchange-specific logic)
  const liquidationRisk = stopLoss ? (
    (side === 'BUY' && currentPrice <= stopLoss) ||
    (side === 'SELL' && currentPrice >= stopLoss)
  ) : false

  return {
    pnlChange,
    pnlPercent,
    riskLevel,
    liquidationRisk,
    currentValue,
    entryValue
  }
}

export function formatPositionImpactSummary(impacts: Array<{
  pnlChange: number
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  liquidationRisk: boolean
}>): {
  totalPnlChange: number
  riskiestLevel: 'low' | 'medium' | 'high' | 'critical'
  hasLiquidationRisk: boolean
  positionCount: number
} {
  const totalPnlChange = impacts.reduce((sum, impact) => sum + impact.pnlChange, 0)

  const riskLevels = ['low', 'medium', 'high', 'critical'] as const
  const riskiestLevel = impacts.reduce((highest, impact) => {
    const currentIndex = riskLevels.indexOf(highest)
    const impactIndex = riskLevels.indexOf(impact.riskLevel)
    return impactIndex > currentIndex ? impact.riskLevel : highest
  }, 'low' as typeof riskLevels[number])

  const hasLiquidationRisk = impacts.some(impact => impact.liquidationRisk)

  return {
    totalPnlChange,
    riskiestLevel,
    hasLiquidationRisk,
    positionCount: impacts.length
  }
}
