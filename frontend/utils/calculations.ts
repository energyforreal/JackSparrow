export function calculatePnL(entryPrice: number, currentPrice: number, quantity: number, side: string): number {
  if (side === 'BUY') {
    return (currentPrice - entryPrice) * quantity
  } else {
    return (entryPrice - currentPrice) * quantity
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
  stopLoss?: number
): {
  pnlChange: number
  pnlPercent: number
  riskLevel: 'low' | 'medium' | 'high' | 'critical'
  liquidationRisk: boolean
  currentValue: number
  entryValue: number
} {
  // Calculate P&L change
  const pnlChange = side === 'BUY'
    ? (currentPrice - entryPrice) * quantity
    : (entryPrice - currentPrice) * quantity

  // Calculate position values
  const entryValue = entryPrice * quantity
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
