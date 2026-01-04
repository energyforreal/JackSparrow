import { useState, useEffect, useRef, useCallback } from 'react'

interface WebSocketMessage {
  type: string
  data?: unknown
  [key: string]: unknown
}

interface UseWebSocketReturn {
  isConnected: boolean
  lastMessage: WebSocketMessage | null
  sendMessage: (message: unknown) => void
  error: Error | null
}

// Channels to subscribe to for real-time updates
const SUBSCRIBE_CHANNELS = [
  'agent_state',
  'signal_update',
  'reasoning_chain_update',
  'model_prediction_update',
  'market_tick',
  'trade_executed',
  'portfolio_update',
  'health_update',
]

export function useWebSocket(url: string): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [isSubscribed, setIsSubscribed] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()
  const subscribedChannelsRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    // Validate WebSocket URL
    if (!url) {
      const errorMessage = process.env.NODE_ENV === 'production'
        ? 'WebSocket URL is not configured. Set NEXT_PUBLIC_WS_URL environment variable in production.'
        : 'WebSocket URL is not configured'
      
      const wsError = new Error(errorMessage)
      setError(wsError)
      
      // Fail loudly in production
      if (process.env.NODE_ENV === 'production') {
        console.error('CRITICAL: WebSocket URL is missing in production:', wsError.message)
        // Optionally throw to prevent silent failures
        // throw wsError
      }
      return
    }
    
    // Validate URL format
    try {
      const urlObj = new URL(url)
      if (!['ws:', 'wss:'].includes(urlObj.protocol)) {
        const errorMessage = `Invalid WebSocket URL protocol: ${urlObj.protocol}. Must be ws:// or wss://`
        const wsError = new Error(errorMessage)
        setError(wsError)
        console.error('Invalid WebSocket URL:', errorMessage)
        return
      }
    } catch (urlError) {
      const errorMessage = `Invalid WebSocket URL format: ${url}`
      const wsError = new Error(errorMessage)
      setError(wsError)
      console.error('Invalid WebSocket URL format:', errorMessage)
      return
    }

    const baseDelay = 1000 // 1 second
    const maxDelay = 5000 // 5 seconds (reduced from 60s for faster reconnection)
    let reconnectAttempts = 0
    let shouldReconnect = true

    const calculateBackoffDelay = (attempts: number): number => {
      // Exponential backoff: baseDelay * 2^attempts, capped at maxDelay
      const delay = baseDelay * Math.pow(2, attempts)
      return Math.min(delay, maxDelay)
    }

    const connect = () => {
      if (!shouldReconnect) return

      try {
        const ws = new WebSocket(url)
        wsRef.current = ws
        setError(null)

        ws.onopen = () => {
          setIsConnected(true)
          reconnectAttempts = 0 // Reset on successful connection
          setError(null)
          console.log('[WebSocket] ✅ Connected to:', url)

          // Subscribe to all required channels when connection opens
          try {
            const subscribeMessage = {
              action: 'subscribe',
              channels: SUBSCRIBE_CHANNELS,
            }
            ws.send(JSON.stringify(subscribeMessage))
            console.log('[WebSocket] 📤 Sent subscription:', SUBSCRIBE_CHANNELS)
          } catch (subError) {
            console.error('[WebSocket] ❌ Failed to send subscribe message:', subError)
          }
        }

        ws.onmessage = (event) => {
          // WS MESSAGE: Debug log for message tracking
          console.log('WS MESSAGE:', event.data)

          try {
            const rawMessage = JSON.parse(event.data) as WebSocketMessage & {
              server_timestamp_ms?: number
            }

            // Special logging for market_tick messages
            if (rawMessage.type === 'market_tick') {
              console.log('[useWebSocket] Received market_tick:', rawMessage.data)
            }
            const message = JSON.parse(event.data) as WebSocketMessage & {
              server_timestamp_ms?: number
            }
            
            // Validate message timestamp to detect stale messages
            const staleThresholdMs = 10000 // 10 seconds
            if (message.server_timestamp_ms) {
              const now = Date.now()
              const age = now - message.server_timestamp_ms
              
              if (age > staleThresholdMs) {
                if (process.env.NODE_ENV === 'development') {
                  console.warn('[useWebSocket] Stale message detected:', {
                    message_type: message.type,
                    age_seconds: age / 1000,
                    threshold_seconds: staleThresholdMs / 1000,
                    server_timestamp_ms: message.server_timestamp_ms,
                    current_time_ms: now
                  })
                }
                // Still process the message but log warning
                // In production, you might want to reject stale messages
              }
            }
            
            setLastMessage(message)
            setError(null)
            
            // Handle subscription confirmation
            if (message.type === 'subscribed') {
              const channels = (message.channels as string[]) || []
              subscribedChannelsRef.current = new Set(channels)
              setIsSubscribed(true)

              console.log('[useWebSocket] Successfully subscribed to channels:', channels)
              console.log('[useWebSocket] market_tick included:', channels.includes('market_tick'))
            }
            
            // Handle time sync messages
            if (message.type === 'time_sync' && message.data) {
              const timeSyncHandler = (window as any).__systemClockSync
              if (timeSyncHandler && typeof timeSyncHandler === 'function') {
                timeSyncHandler(message.data)
              }
            }
          } catch (e) {
            const parseError = e instanceof Error ? e : new Error('Unknown parsing error')
            setError(parseError)
            console.error('Error parsing WebSocket message:', parseError)
          }
        }

        ws.onerror = (event) => {
          const wsError = new Error('WebSocket connection error')
          setError(wsError)
          console.error('WebSocket error:', event)
        }

        ws.onclose = (event) => {
          setIsConnected(false)
          setIsSubscribed(false) // Reset subscription status on disconnect
          subscribedChannelsRef.current.clear()
          
          // Only reconnect if not a normal closure and should reconnect
          if (shouldReconnect && event.code !== 1000) {
            const delay = calculateBackoffDelay(reconnectAttempts)
            reconnectAttempts++
            
            // WS CLOSED: Log disconnection with retry delay info
            console.warn(`WS CLOSED — reconnecting in ${delay}ms (attempt ${reconnectAttempts})`)
            
            console.log(
              `WebSocket closed. Reconnecting in ${delay}ms (attempt ${reconnectAttempts})...`
            )
            
            reconnectTimeoutRef.current = setTimeout(() => {
              connect()
            }, delay)
          }
        }
      } catch (error) {
        const connError = error instanceof Error ? error : new Error('Unknown connection error')
        setError(connError)
        console.error('WebSocket connection error:', connError)
        
        if (shouldReconnect) {
          const delay = calculateBackoffDelay(reconnectAttempts)
          reconnectAttempts++
          reconnectTimeoutRef.current = setTimeout(connect, delay)
        }
      }
    }

    connect()

    return () => {
      shouldReconnect = false
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close(1000, 'Component unmounting')
        wsRef.current = null
      }
    }
  }, [url])

  // Ensure subscription when connected (backup in case onopen subscription didn't work)
  useEffect(() => {
    if (isConnected && !isSubscribed && wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        const subscribeMessage = {
          action: 'subscribe',
          channels: SUBSCRIBE_CHANNELS,
        }
        wsRef.current.send(JSON.stringify(subscribeMessage))
        
        if (process.env.NODE_ENV === 'development') {
          console.log('[useWebSocket] Re-subscribing to channels (backup):', SUBSCRIBE_CHANNELS)
        }
      } catch (subError) {
        console.error('[useWebSocket] Failed to send subscribe message (backup):', subError)
      }
    }
  }, [isConnected, isSubscribed])

  const sendMessage = useCallback((message: unknown) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      try {
        wsRef.current.send(JSON.stringify(message))
      } catch (error) {
        const sendError = error instanceof Error ? error : new Error('Failed to send message')
        setError(sendError)
        console.error('Error sending WebSocket message:', sendError)
      }
    } else {
      setError(new Error('WebSocket is not connected'))
    }
  }, [])

  return { isConnected, lastMessage, sendMessage, error }
}

