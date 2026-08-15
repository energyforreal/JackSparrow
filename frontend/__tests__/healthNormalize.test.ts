import { mergeHealthPreserveFields, normalizeHealthPayload } from '@/lib/healthNormalize'

describe('normalizeHealthPayload', () => {
  it('copies delta_environment from REST payloads', () => {
    const result = normalizeHealthPayload({
      status: 'healthy',
      health_score: 0.9,
      trading_mode: 'testnet',
      delta_environment: 'india_testnet',
      services: {},
    })
    expect(result?.delta_environment).toBe('india_testnet')
    expect(result?.trading_mode).toBe('testnet')
  })

  it('preserves delta_environment across merges', () => {
    const prev = normalizeHealthPayload({
      status: 'healthy',
      health_score: 0.9,
      delta_environment: 'testnet',
      services: {},
    })!
    const next = normalizeHealthPayload({
      status: 'degraded',
      health_score: 0.7,
      services: {},
    })!
    const merged = mergeHealthPreserveFields(prev, next)
    expect(merged.delta_environment).toBe('testnet')
  })

  it('clears degradation_reasons when a later payload sends an empty list', () => {
    const prev = normalizeHealthPayload({
      status: 'degraded',
      health_score: 0.7,
      degradation_reasons: ['Redis is down'],
      services: {},
    })!
    const next = normalizeHealthPayload({
      status: 'healthy',
      health_score: 1.0,
      degradation_reasons: [],
      services: {},
    })!
    const merged = mergeHealthPreserveFields(prev, next)
    expect(merged.degradation_reasons).toEqual([])
    expect(merged.status).toBe('healthy')
  })

  it('preserves degradation_reasons when the field is omitted', () => {
    const prev = normalizeHealthPayload({
      status: 'degraded',
      health_score: 0.7,
      degradation_reasons: ['Agent service is down'],
      services: {},
    })!
    const next = normalizeHealthPayload({
      status: 'degraded',
      health_score: 0.7,
      services: {},
    })!
    const merged = mergeHealthPreserveFields(prev, next)
    expect(merged.degradation_reasons).toEqual(['Agent service is down'])
  })
})
