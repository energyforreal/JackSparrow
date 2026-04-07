'use client'

import { useEffect, useState } from 'react'
import { getBackendProxyBase } from '@/lib/backendProxy'
import { cn } from '@/lib/utils'

interface ModelsStatusPayload {
  available?: boolean
  agent_state?: string
  model_format?: string | null
  model_nodes?: {
    status?: string
    total_models?: number
    healthy_models?: number
    model_format?: string
  }
}

export function ModelStatusPanel({ className }: { className?: string }) {
  const [data, setData] = useState<ModelsStatusPayload | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    const base = getBackendProxyBase()
    const url = `${base}/api/v1/models/status`
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(url, { cache: 'no-store' })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const j = (await res.json()) as ModelsStatusPayload
        if (!cancelled) setData(j)
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : 'fetch failed')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  if (err) {
    return (
      <p className={cn('text-xs text-muted-foreground', className)}>
        Model status unavailable ({err})
      </p>
    )
  }
  if (!data) {
    return <p className={cn('text-xs text-muted-foreground', className)}>Loading model status…</p>
  }
  const mn = data.model_nodes || {}
  const fmt = data.model_format ?? mn.model_format
  return (
    <div className={cn('rounded-md border bg-card p-2 text-xs', className)}>
      <p className="font-medium">ML models</p>
      <dl className="mt-1 grid grid-cols-2 gap-1">
        <dt className="text-muted-foreground">Agent</dt>
        <dd>{data.agent_state ?? '—'}</dd>
        <dt className="text-muted-foreground">Registry</dt>
        <dd>{mn.status ?? '—'}</dd>
        <dt className="text-muted-foreground">Loaded</dt>
        <dd>
          {mn.healthy_models ?? 0}/{mn.total_models ?? 0} healthy
        </dd>
        <dt className="text-muted-foreground">Format</dt>
        <dd className="font-mono">{fmt ?? '—'}</dd>
      </dl>
    </div>
  )
}
