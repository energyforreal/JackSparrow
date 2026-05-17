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
})
