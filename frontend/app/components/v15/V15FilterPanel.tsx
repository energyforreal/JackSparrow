'use client'

import { cn } from '@/lib/utils'

interface V15FilterPanelProps {
  filters?: Record<string, unknown>
  className?: string
}

export function V15FilterPanel({ filters, className }: V15FilterPanelProps) {
  if (!filters || Object.keys(filters).length === 0) return null
  return (
    <div className={cn('rounded-md border bg-muted/30 p-2 text-xs', className)}>
      <p className="mb-1 font-medium text-muted-foreground">v15 filters</p>
      <ul className="grid grid-cols-1 gap-0.5 sm:grid-cols-2">
        {Object.entries(filters).map(([k, v]) => (
          <li key={k} className="flex justify-between gap-2">
            <span className="text-muted-foreground">{k}</span>
            <span className="font-mono">{String(v)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
