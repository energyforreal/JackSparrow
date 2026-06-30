/** Structural gate category labels and block reason copy. */

export const GATE_CATEGORY_LABELS: Record<string, string> = {
  trend: 'Trend',
  structure: 'Structure',
  breakout: 'Breakout',
  liquidity: 'Liquidity',
  volatility: 'Volatility',
  risk: 'Risk',
}

export const GATE_CATEGORY_ORDER = [
  'trend',
  'liquidity',
  'risk',
  'volatility',
  'structure',
  'breakout',
] as const

export function gateCategoryLabel(key: string): string {
  return GATE_CATEGORY_LABELS[key] ?? key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function formatSetupType(setupType: string | null | undefined): string | null {
  if (!setupType || setupType === 'none') return null
  return setupType.replace(/_/g, ' ')
}
