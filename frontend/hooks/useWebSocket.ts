import { useState, useEffect, useRef } from 'react'

interface UseWebSocketReturn {
  isConnected: boolean
  lastMessage: any
  sendMessage: (message: any) => void
}

export function useWebSocket(url: string): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<any>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout>()

  useEffect(() => {
    let reconnectDelay = 1000

    const connect = () => {
      try {
        const ws = new WebSocket(url)
        wsRef.current = ws

        ws.onopen = () => {
          setIsConnected(true)
          reconnectDelay = 1000
          console.log('WebSocket connected')
        }

        ws.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data)
            setLastMessage(message)
          } catch (e) {
            console.error('Error parsing WebSocket message:', e)
          }
        }

        ws.onerror = (error) => {
          console.error('WebSocket error:', error)
        }

        ws.onclose = () => {
          setIsConnected(false)
          console.log('WebSocket disconnected, reconnecting...')
          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectDelay = Math.min(reconnectDelay * 2, 30000)
            connect()
          }, reconnectDelay)
        }
      } catch (error) {
        console.error('WebSocket connection error:', error)
        reconnectTimeoutRef.current = setTimeout(connect, reconnectDelay)
      }
    }

    connect()

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [url])

  const sendMessage = (message: any) => {
    if (wsRef.current && isConnected) {
      wsRef.current.send(JSON.stringify(message))
    }
  }

  return { isConnected, lastMessage, sendMessage }
}

