import { GATE_CATEGORY_ORDER, gateCategoryLabel } from './catalogs/gateCatalog'
import type { AgentOverviewInput, GateRowView, GatesView } from './types'

export function resolveGates(input: AgentOverviewInput): GatesView {
  const { signal } = input
  const empty: GatesView = {
    tradeAllowed: false,
    setupType: null,
    rows: [],
  }
  if (!signal) return empty

  const raw = signal.structural_gates as
    | {
        trade_allowed?: boolean
        categories?: Record<string, boolean>
        setup_type?: string
        block_reasons?: string[]
      }
    | undefined

  if (!raw) return empty

  const categories = raw.categories ?? {}
  const rows: GateRowView[] = []

  for (const key of GATE_CATEGORY_ORDER) {
    if (key in categories) {
      const passed = Boolean(categories[key])
      rows.push({
        key,
        label: gateCategoryLabel(key),
        status: passed ? 'pass' : 'fail',
      })
    }
  }

  for (const [key, passed] of Object.entries(categories)) {
    if (GATE_CATEGORY_ORDER.includes(key as (typeof GATE_CATEGORY_ORDER)[number])) continue
    rows.push({
      key,
      label: gateCategoryLabel(key),
      status: passed ? 'pass' : 'fail',
    })
  }

  return {
    tradeAllowed: Boolean(raw.trade_allowed),
    setupType: raw.setup_type ?? null,
    rows,
  }
}
