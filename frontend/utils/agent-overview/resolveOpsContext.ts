import type { AgentOverviewInput, OpsContextView } from './types'

function serviceLatency(
  health: AgentOverviewInput['health'],
  name: string
): number | null {
  if (!health?.services) return null
  const services = health.services
  const entry =
    Array.isArray(services)
      ? services.find((s) => s.name === name)
      : (services as Record<string, { latency_ms?: number }>)[name]
  if (!entry) return null
  const lat =
    typeof entry === 'object' && entry !== null && 'latency_ms' in entry
      ? entry.latency_ms
      : undefined
  return lat != null ? Math.round(Number(lat)) : null
}

function executionP50(health: AgentOverviewInput['health']): number | null {
  if (!health?.services) return null
  const raw = health.services
  const entry =
    Array.isArray(raw)
      ? raw.find((s) => s.name === 'execution_latency')
      : (raw as Record<string, { details?: { risk_approved_to_fill_ms?: { p50?: number } } }>)
          .execution_latency
  if (!entry || typeof entry !== 'object') return null
  const details = 'details' in entry ? entry.details : undefined
  const p50 = details?.risk_approved_to_fill_ms?.p50
  return p50 != null ? Math.round(Number(p50)) : null
}

export function shouldShowOpsStrip(input: AgentOverviewInput): boolean {
  const { signal, agentState } = input
  if (!signal) return false
  const fsm = String(signal.fsm_state || '')
  const lc = String(signal.position_lifecycle || '').toLowerCase()
  return (
    fsm === 'EntryReady' ||
    fsm === 'Managing' ||
    agentState === 'EXECUTING' ||
    agentState === 'TRADING' ||
    lc === 'managing'
  )
}

export function resolveOpsContext(input: AgentOverviewInput): OpsContextView {
  const { health, signal } = input
  const show = shouldShowOpsStrip(input)

  const modeLabel =
    health?.trading_mode === 'testnet' || health?.delta_environment === 'testnet'
      ? 'Delta testnet'
      : health?.trading_mode
        ? `${health.trading_mode} trading`
        : null

  return {
    show,
    tradingReady: health?.trading_ready ?? null,
    modeLabel,
    deltaLatencyMs: serviceLatency(health, 'delta_api'),
    executionP50Ms: executionP50(health),
  }
}
