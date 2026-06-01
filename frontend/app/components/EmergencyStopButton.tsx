'use client'

import { useCallback, useState } from 'react'
import { AlertTriangle } from 'lucide-react'

import { Button } from '@/components/ui/button'

function backendBase(): string {
  return process.env.NEXT_PUBLIC_BACKEND_PROXY_BASE || '/api/backend'
}

export function EmergencyStopButton() {
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const onEmergencyStop = useCallback(async () => {
    if (
      !window.confirm(
        'Emergency stop will flatten all positions and halt the agent. Continue?'
      )
    ) {
      return
    }
    setPending(true)
    setMessage(null)
    try {
      const res = await fetch(`${backendBase()}/api/v1/admin/agent/emergency-stop`, {
        method: 'POST',
        headers: { Accept: 'application/json' },
        credentials: 'include',
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        setMessage(body?.detail || `Emergency stop failed (${res.status})`)
        return
      }
      setMessage(body?.message || 'Emergency stop completed')
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Emergency stop request failed')
    } finally {
      setPending(false)
    }
  }, [])

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        type="button"
        variant="destructive"
        size="sm"
        disabled={pending}
        onClick={onEmergencyStop}
        className="gap-2"
      >
        <AlertTriangle className="h-4 w-4" />
        {pending ? 'Stopping…' : 'Emergency stop'}
      </Button>
      {message ? (
        <span className="max-w-xs text-right text-xs text-muted-foreground">{message}</span>
      ) : null}
    </div>
  )
}
