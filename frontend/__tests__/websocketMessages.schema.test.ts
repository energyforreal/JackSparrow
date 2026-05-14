import { parseWebSocketInbound } from '@/schemas/websocketMessages.zod'

describe('parseWebSocketInbound', () => {
  it('accepts simplified data_update envelope', () => {
    const r = parseWebSocketInbound({
      type: 'data_update',
      resource: 'signal',
      data: { signal: 'BUY' },
      schema_version: 1,
    })
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.data.type).toBe('data_update')
  })

  it('accepts command response', () => {
    const r = parseWebSocketInbound({
      type: 'response',
      success: true,
      request_id: 'rid_1',
      command: 'get_portfolio',
      data: {},
    })
    expect(r.ok).toBe(true)
  })

  it('accepts legacy signal_update before normalizer', () => {
    const r = parseWebSocketInbound({
      type: 'signal_update',
      data: { confidence: 0.5 },
    })
    expect(r.ok).toBe(true)
  })

  it('rejects non-object JSON root', () => {
    const r = parseWebSocketInbound('not-an-object')
    expect(r.ok).toBe(false)
  })
})
