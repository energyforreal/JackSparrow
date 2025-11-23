import { useState, useEffect, useRef } from 'react'
import { apiClient } from '@/services/api'

interface TimeInfo {
  server_time: string
  timestamp_ms: number
  timezone: string
}

interface UseSystemClockReturn {
  currentTime: Date
  isSynced: boolean
  syncError: Error | null
}

/**
 * Hook for managing system clock synchronization with backend.
 * 
 * Features:
 * - Client-side time updates every second
 * - Backend synchronization on mount and every 5 minutes
 * - Clock drift compensation
 * - WebSocket time sync support
 */
export function useSystemClock(): UseSystemClockReturn {
  const [currentTime, setCurrentTime] = useState<Date>(() => new Date())
  const [isSynced, setIsSynced] = useState(false)
  const [syncError, setSyncError] = useState<Error | null>(null)
  
  const offsetRef = useRef<number>(0) // Offset in milliseconds
  const lastSyncRef = useRef<number>(Date.now())
  const syncIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const updateIntervalRef = useRef<NodeJS.Timeout | null>(null)

  /**
   * Sync with backend server time
   */
  const syncWithServer = async (): Promise<void> => {
    try {
      const timeInfo: TimeInfo = await apiClient.getSystemTime()
      const serverTime = new Date(timeInfo.server_time)
      const clientTime = new Date()
      
      // Calculate offset between server and client
      const offset = serverTime.getTime() - clientTime.getTime()
      offsetRef.current = offset
      lastSyncRef.current = Date.now()
      
      // Update current time with offset
      setCurrentTime(new Date(clientTime.getTime() + offset))
      setIsSynced(true)
      setSyncError(null)
      
      console.debug('System clock synced with server', {
        serverTime: timeInfo.server_time,
        offset: offset,
        offsetSeconds: Math.round(offset / 1000)
      })
    } catch (error) {
      const err = error instanceof Error ? error : new Error('Unknown sync error')
      setSyncError(err)
      setIsSynced(false)
      console.warn('Failed to sync system clock:', err)
    }
  }

  /**
   * Handle WebSocket time sync message
   */
  const handleTimeSync = (timeInfo: TimeInfo): void => {
    try {
      const serverTime = new Date(timeInfo.server_time)
      const clientTime = new Date()
      
      // Calculate offset
      const offset = serverTime.getTime() - clientTime.getTime()
      offsetRef.current = offset
      lastSyncRef.current = Date.now()
      
      // Update current time
      setCurrentTime(new Date(clientTime.getTime() + offset))
      setIsSynced(true)
      setSyncError(null)
    } catch (error) {
      console.warn('Failed to process WebSocket time sync:', error)
    }
  }

  // Initial sync on mount
  useEffect(() => {
    syncWithServer()
    
    // Periodic sync every 5 minutes
    syncIntervalRef.current = setInterval(() => {
      syncWithServer()
    }, 5 * 60 * 1000) // 5 minutes
    
    return () => {
      if (syncIntervalRef.current) {
        clearInterval(syncIntervalRef.current)
      }
    }
  }, [])

  // Update time every second with drift compensation
  useEffect(() => {
    updateIntervalRef.current = setInterval(() => {
      const now = Date.now()
      const timeSinceSync = now - lastSyncRef.current
      
      // Apply offset and update time
      const adjustedTime = new Date(now + offsetRef.current)
      setCurrentTime(adjustedTime)
    }, 1000) // Update every second
    
    return () => {
      if (updateIntervalRef.current) {
        clearInterval(updateIntervalRef.current)
      }
    }
  }, [])

  // Expose handleTimeSync for WebSocket integration
  useEffect(() => {
    // Store handler in window for WebSocket hook to access
    // This is a simple way to allow WebSocket messages to update the clock
    ;(window as any).__systemClockSync = handleTimeSync
    
    return () => {
      delete (window as any).__systemClockSync
    }
  }, [])

  return {
    currentTime,
    isSynced,
    syncError
  }
}

