import { useState, useEffect, useRef, useCallback } from 'react'
import {
  logWebSocketMessage,
  logSubscription,
  logCommandRequest,
  logCommandResponse,
  extractCorrelationId,
  LatencyTimer
} from '../utils/communicationLogger'

interface WebSocketMessage {
  type: string
  data?: unknown
  resource?: string  // For simplified format: signal, portfolio, trade, market, etc.
  [key: string]: unknown
}

/**
 * Normalize WebSocket message to unified format.
 * Handles both new simplified envelope format and legacy message types.
 */
function normalizeWebSocketMessage(message: any): WebSocketMessage {
  // New simplified format already has type and resource
  if (message.type && ['data_update', 'agent_update', 'system_update', 'response', 'error'].includes(message.type)) {
    return message
  }
  
  // Legacy format - convert to simplified format
  const legacyType = message.type
  
  // Map legacy types to simplified format
  if (legacyType === 'signal_update' || legacyType === 'reasoning_chain_update' || legacyType === 'model_prediction_update') {
    return {
      ...message,
      type: 'data_update',
      resource: legacyType === 'signal_update' ? 'signal' : 
                legacyType === 'reasoning_chain_update' ? 'signal' : 'model'
    }
  }
  
  if (legacyType === 'portfolio_update' || legacyType === 'trade_executed' || legacyType === 'market_tick') {
    return {
      ...message,
      type: 'data_update',
      resource: legacyType === 'portfolio_update' ? 'portfolio' :
                legacyType === 'trade_executed' ? 'trade' : 'market'
    }
  }
  
  if (legacyType === 'agent_state') {
    return {
      ...message,
      type: 'agent_update',
      resource: 'agent'
    }
  }
  
  if (legacyType === 'health_update' || legacyType === 'time_sync' || legacyType === 'performance_update') {
    return {
      ...message,
      type: 'system_update',
      resource: legacyType === 'health_update' ? 'health' :
                legacyType === 'time_sync' ? 'time' : 'performance'
    }
  }
  
  // Unknown type - return as-is
  return message
}

interface UseWebSocketReturn {
  isConnected: boolean
  lastMessage: WebSocketMessage | null
  sendMessage: (message: unknown) => void
  error: Error | null
}

// Simplified channels - reduced from 8 to 3 core channels
// Backend now uses unified envelope format: data_update, agent_update, system_update
const SUBSCRIBE_CHANNELS = [
  'data_update',      // Replaces: signal_update, portfolio_update, trade_executed, market_tick, reasoning_chain_update, model_prediction_update
  'agent_update',     // Replaces: agent_state
  'system_update',    // Replaces: health_update, time_sync, performance_update
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

            // Log subscription
            logSubscription(SUBSCRIBE_CHANNELS)

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

            // Normalize message format - handle both new simplified format and legacy format
            const message = normalizeWebSocketMessage(rawMessage)

            // Optional agent debug logging for selected messages
            if (
              process.env.NODE_ENV === 'development' &&
              process.env.NEXT_PUBLIC_DEBUG_AGENT_LOGS === 'true'
            ) {
              try {
                if (
                  (message.type === 'data_update' && (message as any).resource === 'signal') ||
                  message.type === 'agent_update'
                ) {
                  fetch('http://127.0.0.1:7242/ingest/7dea5b1b-57ff-4463-be90-44a6ac830f12', {
                    method: 'POST',
                    headers: {
                      'Content-Type': 'application/json',
                      'X-Debug-Session-Id': 'c0204f',
                    },
                    body: JSON.stringify({
                      sessionId: 'c0204f',
                      runId: 'pre-fix',
                      hypothesisId: message.type === 'agent_update' ? 'H4' : 'H2_H5',
                      location: 'frontend/hooks/useWebSocket.ts:onmessage',
                      message: 'ws_inbound',
                      data: {
                        type: message.type,
                        resource: (message as any).resource,
                        hasData: !!(message as any).data,
                      },
                      timestamp: Date.now(),
                    }),
                  }).catch(() => {})
                }
              } catch {
                // Logging must never affect WebSocket handling
              }
            }

            // Log inbound WebSocket message
            logWebSocketMessage(
              'inbound',
              message.type,
              rawMessage, // Log original message for full payload
              {
                resource: message.resource,
                correlationId: extractCorrelationId(message)
              }
            )

            // Validate message timestamp to detect stale messages
            const staleThresholdMs = 10000 // 10 seconds
            if ((message as { server_timestamp_ms?: number }).server_timestamp_ms) {
              const now = Date.now()
              const age =
                now -
                (message as { server_timestamp_ms?: number }).server_timestamp_ms!
              
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
            }

            // Handle command responses
            if (message.type === 'response') {
              const requestId = extractCorrelationId(message) || ''
              const command = (message as any).command || 'unknown'
              const success = (message as any).success !== false
              const error = success ? undefined : (message as any).error

              logCommandResponse(
                command,
                (message as any).data,
                requestId,
                undefined, // latency not tracked on frontend
                error
              )
            }

            // Handle time sync messages (both new and legacy format)
            if ((message.type === 'system_update' && (message as any).resource === 'time') ||
                message.type === 'time_sync') {
              const timeData = (message as any).data || (message as any).data
              if (timeData) {
                const timeSyncHandler = (window as any).__systemClockSync
                if (timeSyncHandler && typeof timeSyncHandler === 'function') {
                  timeSyncHandler(timeData)
                }
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

        // Log subscription (backup)
        logSubscription(SUBSCRIBE_CHANNELS)

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
        const messageData = message as any;

        // Log outgoing message
        if (messageData.action === 'command') {
          // Log command request
          logCommandRequest(
            messageData.command,
            messageData.parameters || {},
            messageData.request_id || extractCorrelationId(messageData)
          );
        } else {
          // Log other WebSocket messages
          logWebSocketMessage(
            'outbound',
            messageData.action || 'unknown',
            messageData,
            {
              correlationId: extractCorrelationId(messageData)
            }
          );
        }

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

