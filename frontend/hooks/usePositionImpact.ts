import { useMemo } from 'react'
import { Position, PositionImpact, EnhancedTickerData } from '@/types'
import {
  calculatePositionImpact,
  formatPositionImpactSummary,
} from '@/utils/calculations'

export function usePositionImpact(
  positions: Position[],
  tickerData: EnhancedTickerData | null
): {
  positionImpacts: PositionImpact[]
  summary: {
    totalPnlChange: number
    riskiestLevel: 'low' | 'medium' | 'high' | 'critical'
    hasLiquidationRisk: boolean
    positionCount: number
  }
  affectedPositions: PositionImpact[]
} {
  const positionImpacts = useMemo(() => {
    if (!tickerData) {
      return []
    }

    return positions
      .filter(position => position.symbol === tickerData.symbol)
      .map(position => {
        const entryPrice = typeof position.entry_price === 'string'
          ? parseFloat(position.entry_price)
          : position.entry_price

        const quantity = typeof position.quantity === 'string'
          ? parseFloat(position.quantity)
          : position.quantity

        const stopLoss = position.stop_loss
          ? (typeof position.stop_loss === 'string' ? parseFloat(position.stop_loss) : position.stop_loss)
          : undefined

        if (isNaN(entryPrice) || isNaN(quantity)) {
          console.warn('Invalid position data:', position)
          return null
        }

        const impact = calculatePositionImpact(
          entryPrice,
          tickerData.price,
          quantity,
          position.side,
          stopLoss
        )

        return {
          positionId: position.position_id,
          symbol: position.symbol,
          pnlChange: impact.pnlChange,
          pnlPercent: impact.pnlPercent,
          riskLevel: impact.riskLevel,
          liquidationRisk: impact.liquidationRisk,
          currentValue: impact.currentValue,
          entryValue: impact.entryValue
        }
      })
      .filter((impact): impact is PositionImpact => impact !== null)
  }, [positions, tickerData])

  const summary = useMemo(() => {
    return formatPositionImpactSummary(positionImpacts)
  }, [positionImpacts])

  return {
    positionImpacts,
    summary,
    affectedPositions: positionImpacts // alias for backward compatibility
  }
}