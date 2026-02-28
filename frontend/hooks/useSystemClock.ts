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
  // Initialize with current time to prevent showing epoch date
  // Will be synced with server after mount, but always show reasonable time
  const [currentTime, setCurrentTime] = useState<Date>(() => {
    // Use current time immediately to avoid showing epoch date
    if (typeof window !== 'undefined') {
      return new Date()
    }
    return new Date(0) // Fallback for SSR
  })
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
      // Even if sync fails, use client time as fallback
      // Reset offset to 0 so we use pure client time
      offsetRef.current = 0
      lastSyncRef.current = Date.now()
      setCurrentTime(new Date())
      console.warn('Failed to sync system clock, using client time:', err)
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

  // Initial sync on mount (client-side only)
  useEffect(() => {
    // Ensure we have a valid current time immediately
    if (currentTime.getTime() === 0 || currentTime.getFullYear() < 2020) {
      setCurrentTime(new Date())
    }
    
    // Then sync with server (non-blocking)
    syncWithServer().catch(() => {
      // Error already handled in syncWithServer
    })
    
    // Periodic sync every 5 minutes
    syncIntervalRef.current = setInterval(() => {
      syncWithServer().catch(() => {
        // Error already handled in syncWithServer
      })
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
      // Always ensure we have a valid date (not epoch)
      const adjustedTime = new Date(now + offsetRef.current)
      if (adjustedTime.getTime() > 0 && adjustedTime.getFullYear() >= 2020) {
        setCurrentTime(adjustedTime)
      } else {
        // Fallback to current time if adjusted time is invalid
        setCurrentTime(new Date())
      }
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

