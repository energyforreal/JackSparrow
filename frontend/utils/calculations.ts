export function calculatePnL(entryPrice: number, currentPrice: number, quantity: number, side: string): number {
  if (side === 'BUY') {
    return (currentPrice - entryPrice) * quantity
  } else {
    return (entryPrice - currentPrice) * quantity
  }
}

export function calculatePnLPercent(entryPrice: number, currentPrice: number, side: string): number {
  if (side === 'BUY') {
    return ((currentPrice - entryPrice) / entryPrice) * 100
  } else {
    return ((entryPrice - currentPrice) / entryPrice) * 100
  }
}

export function calculateReturn(initial: number, current: number): number {
  return ((current - initial) / initial) * 100
}

