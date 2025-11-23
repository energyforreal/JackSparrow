export interface WebSocketMessage {
  type: string
  data: unknown
}

export class WebSocketClient {
  private ws: WebSocket | null = null
  private url: string
  private reconnectDelay: number = 1000
  private reconnectTimeout: NodeJS.Timeout | null = null
  private listeners: Map<string, Set<(data: unknown) => void>> = new Map()

  constructor(url: string) {
    this.url = url
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return
    }

    try {
      this.ws = new WebSocket(this.url)

      this.ws.onopen = () => {
        console.log('WebSocket connected')
        this.reconnectDelay = 1000
      }

      this.ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          const listeners = this.listeners.get(message.type) || new Set()
          listeners.forEach((listener) => listener(message.data))
        } catch (error) {
          console.error('Error parsing WebSocket message:', error)
        }
      }

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error)
      }

      this.ws.onclose = () => {
        console.log('WebSocket disconnected, reconnecting...')
        this.reconnectTimeout = setTimeout(() => {
          this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000)
          this.connect()
        }, this.reconnectDelay)
      }
    } catch (error) {
      console.error('WebSocket connection error:', error)
    }
  }

  disconnect() {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }

  on(event: string, callback: (data: unknown) => void) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)!.add(callback)
  }

  off(event: string, callback: (data: unknown) => void) {
    const listeners = this.listeners.get(event)
    if (listeners) {
      listeners.delete(callback)
    }
  }

  send(message: WebSocketMessage | Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
    }
  }
}

