'use client'

import { useEffect, useState } from 'react'
import { getBackendProxyBase } from '@/lib/backendProxy'
import { cn } from '@/lib/utils'

interface AgentStatusPayload {
  available?: boolean
  agent_state?: string
}

export function ModelStatusPanel({ className }: { className?: string }) {
  const [data, setData] = useState<AgentStatusPayload | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const base = getBackendProxyBase()
    const url = `${base}/api/v1/models/status`
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(url, { cache: 'no-store' })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const j = (await res.json()) as AgentStatusPayload
        if (!cancelled) setData(j)
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : 'fetch failed')
      }
    })()
    return () => { cancelled = true }
  }, [])

  if (err) {
    return (
      <p className={cn('text-xs text-muted-foreground', className)}>
        Agent status unavailable ({err})
      </p>
    )
  }
  if (!data) {
    return <p className={cn('text-xs text-muted-foreground', className)}>Loading agent status…</p>
  }

  return (
    <div className={cn('rounded-md border bg-card p-2 text-xs', className)}>
      <p className="font-medium">Agent status</p>
      <dl className="mt-1 grid grid-cols-2 gap-1">
        <dt className="text-muted-foreground">State</dt>
        <dd>{data.agent_state ?? '—'}</dd>
        <dt className="text-muted-foreground">Available</dt>
        <dd>{data.available == null ? '—' : data.available ? 'yes' : 'no'}</dd>
      </dl>
    </div>
  )
}
