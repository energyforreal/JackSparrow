/**
 * Normalize backend/WebSocket health payloads for the dashboard.
 * Keeps REST + periodic WS broadcasts consistent with typed UI expectations.
 */

import type { HealthStatus, ServiceStatus } from '@/types'

export function coerceServiceStatus(
  raw: unknown
): 'up' | 'degraded' | 'down' | 'unknown' {
  const s = String(raw ?? 'unknown').toLowerCase().trim()
  if (['up', 'healthy', 'ok', 'running', 'online'].includes(s)) return 'up'
  if (['down', 'offline', 'unhealthy', 'error', 'failed', 'stopped'].includes(s))
    return 'down'
  if (['degraded', 'warning', 'partial', 'marginal'].includes(s)) return 'degraded'
  return 'unknown'
}

export type OverallSystemStatus = 'healthy' | 'degraded' | 'unhealthy'

export function coerceOverallSystemStatus(raw: unknown): OverallSystemStatus {
  const s = String(raw ?? 'degraded').toLowerCase().trim()
  if (s === 'healthy' || s === 'green' || s === 'operational') return 'healthy'
  if (s === 'degraded') return 'degraded'
  if (s === 'unhealthy' || s === 'critical' || s === 'error') return 'unhealthy'
  return 'degraded'
}

/** Return a typed HealthStatus with coerced statuses and sane defaults for services. */
export function normalizeHealthPayload(raw: unknown): HealthStatus | null {
  if (!raw || typeof raw !== 'object') return null

  const h = raw as Record<string, unknown>
  const merged: Partial<HealthStatus> = {}

  if (typeof h.status === 'string') {
    merged.status = coerceOverallSystemStatus(h.status)
  }
  const overallAlt = (h as { overall_status?: unknown }).overall_status
  if (merged.status === undefined && typeof overallAlt === 'string') {
    merged.status = coerceOverallSystemStatus(overallAlt)
  }

  if (typeof h.health_score === 'number' && Number.isFinite(h.health_score)) {
    merged.health_score = h.health_score
  }
  if (typeof h.score === 'number' && Number.isFinite(h.score)) {
    merged.score = h.score
  }
  if (Array.isArray(h.degradation_reasons)) {
    merged.degradation_reasons = h.degradation_reasons.filter(
      (x): x is string => typeof x === 'string'
    )
  }
  if (typeof h.agent_state === 'string') {
    merged.agent_state = h.agent_state
  }
  if (typeof h.trading_ready === 'boolean') {
    merged.trading_ready = h.trading_ready
  }
  if (typeof h.trading_mode === 'string' && h.trading_mode.trim()) {
    merged.trading_mode = h.trading_mode.trim().toLowerCase()
  }
  if (typeof h.delta_environment === 'string' && h.delta_environment.trim()) {
    merged.delta_environment = h.delta_environment.trim().toLowerCase()
  }
  if (h.ml_models && typeof h.ml_models === 'object') {
    merged.ml_models = h.ml_models as Record<string, unknown>
  }

  let ts = h.timestamp
  if (ts !== undefined && ts !== null) {
    merged.timestamp = ts as HealthStatus['timestamp']
  }

  const rawServices = h.services as Record<string, unknown> | undefined
  const servicesRecord: Record<string, ServiceStatus> = {}
  if (rawServices && typeof rawServices === 'object') {
    for (const [name, svc] of Object.entries(rawServices)) {
      if (!svc || typeof svc !== 'object') continue
      const o = svc as Record<string, unknown>
      servicesRecord[name] = {
        status: coerceServiceStatus(o.status),
        latency_ms:
          typeof o.latency_ms === 'number' ? o.latency_ms : undefined,
        error: typeof o.error === 'string' ? o.error : undefined,
        details:
          o.details && typeof o.details === 'object'
            ? (o.details as ServiceStatus['details'])
            : undefined,
      }
    }
  }

  merged.services = servicesRecord

  if (
    merged.status === undefined &&
    typeof merged.health_score === 'number' &&
    Number.isFinite(merged.health_score)
  ) {
    const hs = merged.health_score
    merged.status =
      hs >= 0.9 ? 'healthy' : hs >= 0.6 ? 'degraded' : 'unhealthy'
  }

  return merged as HealthStatus
}

/** Merge successive health payloads without dropping fields some streams omit sporadically. */
export function mergeHealthPreserveFields(
  previous: HealthStatus | null,
  next: HealthStatus
): HealthStatus {
  if (!previous) return next
  return {
    ...next,
    trading_ready:
      typeof next.trading_ready === 'boolean'
        ? next.trading_ready
        : previous.trading_ready,
    trading_mode:
      next.trading_mode !== undefined ? next.trading_mode : previous.trading_mode,
    delta_environment:
      next.delta_environment !== undefined ? next.delta_environment : previous.delta_environment,
    ml_models: next.ml_models !== undefined ? next.ml_models : previous.ml_models,
    agent_state: next.agent_state !== undefined ? next.agent_state : previous.agent_state,
    degradation_reasons:
      Array.isArray(next.degradation_reasons) && next.degradation_reasons.length > 0
        ? next.degradation_reasons
        : previous.degradation_reasons,
  }
}
