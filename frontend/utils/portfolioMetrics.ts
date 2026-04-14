/**
 * Portfolio ROE helpers. Margin and unrealized PnL are expected in INR (same FX snapshot from backend).
 */

/**
 * Return unrealized PnL / margin as a ratio in (-∞, ∞), or null if the ratio is undefined (no margin).
 */
export function unrealizedPnlPercentOnMargin(
  unrealizedInr: number,
  marginUsedInr: number
): number | null {
  if (!Number.isFinite(unrealizedInr) || !Number.isFinite(marginUsedInr)) {
    return null
  }
  if (marginUsedInr <= 0) {
    return null
  }
  return unrealizedInr / marginUsedInr
}
