/**
 * Resolve WebSocket URL for the FastAPI `/ws` endpoint.
 * Single source of truth for dashboard + ticker components.
 */
export function resolveWebSocketUrl(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL
  }

  if (process.env.NODE_ENV === 'development') {
    return 'ws://localhost:8000/ws'
  }

  try {
    if (process.env.NEXT_PUBLIC_API_URL) {
      const api = new URL(process.env.NEXT_PUBLIC_API_URL)
      const wsProtocol = api.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${wsProtocol}//${api.host}/ws`
    }

    if (typeof window !== 'undefined') {
      const { protocol, host } = window.location
      const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:'
      const hostOnly = host.split(':')[0]
      const port = '8000'
      return `${wsProtocol}//${hostOnly}:${port}/ws`
    }
  } catch {
    // fall through
  }

  return ''
}
