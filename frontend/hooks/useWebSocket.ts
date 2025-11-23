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

export function useWebSocket(url: string): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()

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
    const maxDelay = 60000 // 60 seconds
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
        }

        ws.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data) as WebSocketMessage
            setLastMessage(message)
            setError(null)
            
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
          
          // Only reconnect if not a normal closure and should reconnect
          if (shouldReconnect && event.code !== 1000) {
            const delay = calculateBackoffDelay(reconnectAttempts)
            reconnectAttempts++
            
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

